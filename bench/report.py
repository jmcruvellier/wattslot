"""Tableau Markdown des résultats du banc (un ou plusieurs fichiers JSON de ``bench.run``).

python -m bench.report bench-pyoxigraph.json bench-serveur.json
"""

import json
import sys
from pathlib import Path


def n(value: float) -> str:
    """Nombre avec séparateur de milliers à la française."""
    return f"{value:,}".replace(",", chr(0x202F))


def table(results: list[dict]) -> str:  # type: ignore[type-arg]
    lines = []
    for r in results:
        lines.append(f"### {r['backend']} — profil {r['profile']} ({r['machine']})\n")
        lines.append("| Requête | v1 (un graphe) | Partitionné | Lignes v1 / partitionné |")
        lines.append("|---|---|---|---|")
        for name, single in r["queries"]["single"].items():
            part = r["queries"]["partitioned"][name]
            lines.append(
                f"| {name} | {single['median_s']:.3f} s | {part['median_s']:.3f} s "
                f"| {single['rows']} / {part['rows']} |"
            )
        lines.append("")
        lines.append("| Chargement | Triplets | Durée | Triplets/s |")
        lines.append("|---|---|---|---|")
        for name, load in r["loads"].items():
            lines.append(
                f"| {name} | {n(load['triples'])} | {load['seconds']} s "
                f"| {n(load['triples_per_s'])} |"
            )
        ing = r["ingestion"]
        lines.append("")
        lines.append(
            f"Temps réel : {n(ing['observations_per_day'])} observations "
            f"({n(ing['triples_per_day'])} triplets) par jour ; lot d'une minute "
            f"({ing['batch_triples']} triplets) écrit en {ing['batch_median_s']} s (médiane), "
            f"{ing['batch_max_s']} s au plus. Suppression d'une journée de brut : "
            f"{r['retention']['remove_raw_day_s']} s."
        )
        sizes = ", ".join(f"{k} {v} Mo" for k, v in r["sizes_mb"].items() if v is not None)
        if sizes:
            lines.append(f"Taille sur disque : {sizes}.")
        if r.get("peak_memory_mb"):
            lines.append(f"Mémoire maximale : {r['peak_memory_mb']:.0f} Mo.")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    print(table([json.loads(Path(p).read_text("utf-8")) for p in sys.argv[1:]]))
