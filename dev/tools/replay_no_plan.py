"""Rejeu d'un problème sans plan capturé par l'application (lot 7.3, ``planning/capture.py``).

    python dev/tools/replay_no_plan.py <données>/diagnostic/no-plan-….pickle

Relance le solveur sur le problème et l'objectif capturés, avec la version de HiGHS installée,
et dit s'il rend un plan. La capture vient de la maison qui l'a écrite (noms des équipements,
prévisions) : elle ne va jamais dans le dépôt. Ne relire que des fichiers écrits par
l'application (``pickle`` exécute ce qu'il lit).
"""

import argparse
import sys
import time
from pathlib import Path

import highspy

from wattslot.planning.capture import load
from wattslot.planning.engine import NoPlanError, solve


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("capture", type=Path, help="fichier no-plan-….pickle")
    args = parser.parse_args()
    content = load(args.capture)
    problem, objective = content["problem"], content["objective"]
    print(
        f"Capture du {content['captured_at']} (version {content['version']}) : jour "
        f"{problem.day}, objectif {objective}, {len(problem.tasks)} tâche(s), "
        f"{len(problem.runtimes)} durée(s) à placer, {len(problem.needs)} besoin(s)"
    )
    print(f"HiGHS {highspy.Highs().version()}")  # type: ignore[no-untyped-call]
    began = time.perf_counter()
    try:
        plan = solve(problem, objective)
    except NoPlanError as exc:
        print(f"Toujours sans plan ({time.perf_counter() - began:.1f} s) : {exc}")
        return 1
    print(f"Plan trouvé ({time.perf_counter() - began:.1f} s) : {plan}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
