"""WattSlot : planification énergétique domestique pour Home Assistant."""

from importlib.metadata import PackageNotFoundError, version

# Une seule source pour la version : pyproject.toml, alignée par app/scripts/version.py (lot 6t.1).
try:
    __version__ = version("wattslot")
except PackageNotFoundError:  # code lu sans être installé
    __version__ = "0.0.0"

# Avant tout autre module : sur un processeur sans x86-64-v2, NumPy (chargé par highspy)
# échouerait à l'import avec une trace illisible ; check_numpy explique quoi faire et quitte.
from wattslot.cpu import check_numpy

check_numpy()
