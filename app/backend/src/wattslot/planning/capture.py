"""Capture d'un problème sans plan (lot 7.3), pour le rejouer hors de la maison.

HiGHS déclare parfois impossible un problème qui a toujours une solution (``engine.solve``) :
le problème et l'objectif sont alors écrits dans ``<données>/diagnostic/``, un fichier par
échec, les ``KEEP`` plus récents gardés. Ils restent sur la machine : ils décrivent la maison
(noms des équipements, prévisions), et ne vont ni dans le rapport anonymisé ni dans les
sauvegardes. Rejeu : ``python dev/tools/replay_no_plan.py <fichier>``.

Format : ``pickle`` d'un dictionnaire (``version``, ``captured_at``, ``objective``,
``problem``), relu par la même version de l'application.
"""

import logging
import pickle
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from wattslot import __version__
from wattslot.planning.engine import NoPlanError

logger = logging.getLogger(__name__)

DIRNAME = "diagnostic"
PREFIX = "no-plan-"
KEEP = 10


def save(data_dir: Path, error: NoPlanError, now: datetime | None = None) -> Path | None:
    """Écrit le problème de ``error`` ; ``None`` si l'écriture échoue (jamais d'exception)."""
    now = now or datetime.now(UTC)
    directory = data_dir / DIRNAME
    path = directory / f"{PREFIX}{error.problem.day.isoformat()}-{now:%Y%m%dT%H%M%S%f}.pickle"
    content: dict[str, Any] = {
        "version": __version__,
        "captured_at": now.isoformat(),
        "objective": error.objective,
        "problem": error.problem,
    }
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path.write_bytes(pickle.dumps(content))
        for old in sorted(directory.glob(f"{PREFIX}*.pickle"))[:-KEEP]:
            old.unlink(missing_ok=True)
    except Exception:  # la capture ne doit pas faire échouer le calcul
        logger.exception("Capture du problème sans plan impossible")
        return None
    logger.warning("Problème sans plan du %s capturé : %s", error.problem.day, path)
    return path


def load(path: Path) -> dict[str, Any]:
    """Relit une capture : seulement un fichier écrit par ``save`` (``pickle`` exécute ce qu'il
    lit)."""
    content: dict[str, Any] = pickle.loads(path.read_bytes())
    return content
