"""Arrêt propre et sauvegarde à chaud de l'extension (lot 6t.3)."""

import asyncio
import gc
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import pytest
from fastapi.testclient import TestClient
from websockets.asyncio.server import serve

from tests.fake_home_assistant import TOKEN, default_responses, fake_home_assistant
from wattslot import backup
from wattslot.detection import DeviceKind, Role
from wattslot.home_model import HomeDevice, HomeModel, HomeSensor
from wattslot.home_model import load as load_home
from wattslot.home_model import save as save_home
from wattslot.ingress import SUPERVISOR_INGRESS_ADDRESS
from wattslot.main import create_app
from wattslot.maintenance import Retention, load_retention, save_retention
from wattslot.runtime import HomeAssistantTarget, RunMode, Settings
from wattslot.storage.database import DATABASE_FILENAME, open_database
from wattslot.storage.graph import GRAPH_DIRNAME, GraphStore
from wattslot.storage.raw import RawStores

T0 = datetime(2026, 10, 18, 10, 0, tzinfo=UTC)
LOCAL = ("127.0.0.1", 50000)

MODEL = HomeModel(
    devices=[
        HomeDevice(
            key="solar",
            kind=DeviceKind.SOLAR,
            name="PV",
            sensors=[HomeSensor(entity_id="sensor.pv_power", role=Role.POWER_PRODUCED)],
        )
    ]
)


def _settings(data_dir: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "mode": RunMode.STANDALONE,
        "data_dir": data_dir,
        "static_dir": None,
        "home_assistant": None,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def _home(graph: GraphStore) -> HomeModel | None:
    model = load_home(graph)
    return model if model.devices else None


# --- Arrêt propre ----------------------------------------------------------------------------


def test_shutdown_writes_pending_readings_and_state_to_disk(tmp_path: Path) -> None:
    """Relevés reçus juste avant l'arrêt (encore en file, pas de flush) : sur disque après."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    save_home(GraphStore(data_dir), MODEL)
    responses = default_responses()
    responses["get_states"] = [
        {
            "entity_id": "sensor.pv_power",
            "state": "1200",
            "attributes": {"unit_of_measurement": "W"},
            "lc": T0.timestamp(),
        }
    ]

    async def scenario() -> float:
        async with serve(fake_home_assistant(responses), "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            target = HomeAssistantTarget(f"ws://127.0.0.1:{port}/api/websocket", TOKEN)
            app = create_app(_settings(data_dir, home_assistant=target))
            async with app.router.lifespan_context(app):
                async with asyncio.timeout(5):
                    while app.state.ingestor.status().received < 1:
                        await asyncio.sleep(0.01)
                began = time.monotonic()
            return time.monotonic() - began

    elapsed = asyncio.run(scenario())
    gc.collect()  # magasins de l'application libérés, comme à la fin du processus

    assert elapsed < 20  # délai d'arrêt de l'extension : 30 s, dont 10 pour uvicorn
    assert RawStores(data_dir).count(T0.date()) == 1
    database = open_database(data_dir)
    assert database.execute("SELECT entity_id FROM ingestion_state").fetchall() == [
        ("sensor.pv_power",)
    ]


# --- Copie figée -----------------------------------------------------------------------------


def _filled(data_dir: Path) -> tuple[sqlite3.Connection, GraphStore]:
    data_dir.mkdir(parents=True, exist_ok=True)
    database = open_database(data_dir)
    graph = GraphStore(data_dir)
    save_retention(database, Retention(raw_days=5))
    save_home(graph, MODEL)
    return database, graph


def test_snapshot_does_not_change_while_the_application_keeps_writing(tmp_path: Path) -> None:
    database, graph = _filled(tmp_path)

    target = backup.prepare(tmp_path, database, graph)
    save_retention(database, Retention(raw_days=7))
    save_home(graph, HomeModel())

    assert target == tmp_path / backup.SNAPSHOT_DIRNAME
    assert not (tmp_path / backup.PARTIAL_DIRNAME).exists()
    copy = sqlite3.connect(target / backup.SNAPSHOT_DATABASE)
    assert load_retention(copy).raw_days == 5
    copy.close()
    assert _home(_open_graph(target / backup.SNAPSHOT_GRAPH)) == MODEL


def _open_graph(path: Path) -> GraphStore:
    """Magasin copié, ouvert là où il est (``GraphStore`` ajoute ``oxigraph``)."""
    restored = path.parent / "opened"
    restored.mkdir()
    path.rename(restored / GRAPH_DIRNAME)
    return GraphStore(restored)


def test_restore_puts_the_snapshot_back_in_place(tmp_path: Path) -> None:
    source = tmp_path / "source"
    database, graph = _filled(source)
    backup.prepare(source, database, graph)
    database.close()
    # Restauration par HA : seul backup/ est dans la sauvegarde.
    restored = tmp_path / "restored"
    restored.mkdir()
    (source / backup.SNAPSHOT_DIRNAME).rename(restored / backup.SNAPSHOT_DIRNAME)

    assert backup.restore_snapshot(restored)

    assert not (restored / backup.SNAPSHOT_DIRNAME).exists()
    assert load_retention(open_database(restored)).raw_days == 5
    assert _home(GraphStore(restored)) == MODEL


def test_a_left_over_snapshot_is_removed_without_touching_live_data(tmp_path: Path) -> None:
    database, graph = _filled(tmp_path)
    backup.prepare(tmp_path, database, graph)
    (tmp_path / backup.PARTIAL_DIRNAME).mkdir()
    save_retention(database, Retention(raw_days=7))
    database.close()
    del graph

    assert not backup.restore_snapshot(tmp_path)

    assert not (tmp_path / backup.SNAPSHOT_DIRNAME).exists()
    assert not (tmp_path / backup.PARTIAL_DIRNAME).exists()
    assert load_retention(open_database(tmp_path)).raw_days == 7


def test_prepare_replaces_a_previous_snapshot(tmp_path: Path) -> None:
    database, graph = _filled(tmp_path)
    backup.prepare(tmp_path, database, graph)
    save_retention(database, Retention(raw_days=7))

    target = backup.prepare(tmp_path, database, graph)

    copy = sqlite3.connect(target / backup.SNAPSHOT_DATABASE)
    assert load_retention(copy).raw_days == 7
    copy.close()


# --- Routes et commandes ----------------------------------------------------------------------


@pytest.mark.parametrize("mode", [RunMode.STANDALONE, RunMode.ADDON])
def test_backup_routes_from_the_machine_itself(tmp_path: Path, mode: RunMode) -> None:
    data_dir = tmp_path / "data"
    with TestClient(create_app(_settings(data_dir, mode=mode)), client=LOCAL) as api:
        prepared = api.post("/api/backup/prepare")
        snapshot = data_dir / backup.SNAPSHOT_DIRNAME
        assert prepared.status_code == 200
        assert (snapshot / backup.SNAPSHOT_DATABASE).is_file()
        assert (snapshot / backup.SNAPSHOT_GRAPH).is_dir()

        assert api.post("/api/backup/finish").status_code == 200
        assert not snapshot.exists()


@pytest.mark.parametrize(
    ("mode", "address"),
    [(RunMode.ADDON, SUPERVISOR_INGRESS_ADDRESS), (RunMode.STANDALONE, "192.0.2.20")],
)
def test_backup_routes_refuse_other_addresses(tmp_path: Path, mode: RunMode, address: str) -> None:
    data_dir = tmp_path / "data"
    app = create_app(_settings(data_dir, mode=mode))
    with TestClient(app, client=(address, 50000)) as api:
        assert api.post("/api/backup/prepare").status_code == 403
        assert api.post("/api/backup/finish").status_code == 403
    assert not (data_dir / backup.SNAPSHOT_DIRNAME).exists()


def test_backup_files_excluded_from_home_assistant_backups() -> None:
    """Le Supervisor compare ``backup_exclude`` à la fin du chemin (``PurePath.match``) : les
    fichiers vivants sont exclus, la copie figée non."""
    config = Path(__file__).parents[3] / "ha-addon" / "wattslot" / "config.yaml"
    lines = config.read_text(encoding="utf-8").splitlines()
    excludes: list[str] = []
    for line in lines[lines.index("backup_exclude:") + 1 :]:
        if not line.startswith("  - "):
            break
        excludes.append(line[4:])

    def excluded(path: str) -> bool:
        return any(PurePosixPath("/data", path).match(e) for e in excludes)

    for live in ("raw", GRAPH_DIRNAME, DATABASE_FILENAME, f"{DATABASE_FILENAME}-wal"):
        assert excluded(live), live
    for kept in (
        backup.SNAPSHOT_DIRNAME,
        f"{backup.SNAPSHOT_DIRNAME}/{backup.SNAPSHOT_GRAPH}",
        f"{backup.SNAPSHOT_DIRNAME}/{backup.SNAPSHOT_DATABASE}",
        "options.json",
    ):
        assert not excluded(kept), kept


def test_command_fails_when_the_application_does_not_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(backup, "LOCAL_URL", "http://127.0.0.1:9/api/backup")

    assert backup.main(["prepare"]) == 1
    assert backup.main(["other"]) == 2
