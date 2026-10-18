"""Cache de l'interface (lot 7.1) : page d'accueil revalidée, fichiers à empreinte gardés un an."""

from pathlib import Path

from fastapi.testclient import TestClient

from wattslot.main import create_app
from wattslot.runtime import RunMode, Settings


def test_the_page_is_revalidated_and_the_fingerprinted_files_are_kept(tmp_path: Path) -> None:
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text('<script src="assets/index-abc123.js"></script>', "utf-8")
    (static / "assets" / "index-abc123.js").write_text("console.log(1)", encoding="utf-8")
    settings = Settings(
        mode=RunMode.STANDALONE, data_dir=tmp_path / "data", static_dir=static, home_assistant=None
    )

    with TestClient(create_app(settings)) as client:
        page = client.get("/")
        script = client.get("/assets/index-abc123.js")
        # Une mise à jour change le nom du script : la page doit toujours être relue.
        revalidated = client.get("/", headers={"If-None-Match": page.headers["etag"]})

    assert page.headers["cache-control"] == "no-cache"
    assert script.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert revalidated.status_code == 304
    assert revalidated.headers["cache-control"] == "no-cache"
