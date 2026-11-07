"""Vérification du processeur au démarrage : NumPy exige le niveau x86-64-v2.

highspy (moteur du calcul) charge NumPy, dont les roues récentes sont compilées pour
x86-64-v2 (SSE4.2, POPCNT…). Sous Proxmox, une machine virtuelle au type de CPU ``kvm64`` ou
``qemu64`` cache ces instructions même quand le processeur hôte les a : NumPy lève alors une
``RuntimeError`` à l'import, et le journal ne montre qu'une trace Python. On la remplace par
un message qui dit quoi faire, en anglais puis en français (le journal de l'extension est lu
par l'utilisateur), et on s'arrête.
"""

import sys
from typing import TextIO

DOC_URL = "https://github.com/jmcruvellier/wattslot/blob/main/docs/troubleshooting.md"

MESSAGE = f"""
WattSlot cannot start: this processor does not report the x86-64-v2 instructions
required by NumPy (used by the planning engine).
On Proxmox, set the CPU type of the virtual machine to "host" (or "x86-64-v2-AES"):
VM > Hardware > Processors > Type, then stop and start the virtual machine.
See {DOC_URL}

WattSlot ne peut pas démarrer : ce processeur ne déclare pas les instructions x86-64-v2
qu'exige NumPy (utilisé par le moteur du calcul).
Sous Proxmox, mettez le type de CPU de la machine virtuelle sur « host » (ou « x86-64-v2-AES ») :
VM > Matériel > Processeurs > Type, puis arrêtez et relancez la machine virtuelle.
Voir {DOC_URL.replace("/docs/", "/docs/fr/")}
"""


def is_unsupported_cpu(error: BaseException) -> bool:
    """Vrai si l'erreur est le refus de NumPy face à un processeur sans x86-64-v2."""
    return isinstance(error, RuntimeError) and "baseline optimizations" in str(error)


def check_numpy(stream: TextIO = sys.stderr) -> None:
    """Charge NumPy ; sur un processeur non pris en charge, explique et quitte (code 1).

    Toute autre erreur remonte telle quelle.
    """
    try:
        import numpy  # noqa: F401  (chargé ici pour attraper l'erreur avant highspy)
    except RuntimeError as error:
        if not is_unsupported_cpu(error):
            raise
        stream.write(MESSAGE)
        stream.flush()
        raise SystemExit(1) from error
