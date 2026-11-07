"""Vérification du processeur au démarrage (NumPy et x86-64-v2)."""

import builtins
import io
from typing import Any

import pytest

from wattslot import cpu

NUMPY_ERROR = (
    "NumPy was built with baseline optimizations: \n(X86_V2) but your machine "
    "doesn't support:\n(X86_V2)."
)


def _failing_import(error: BaseException) -> Any:
    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "numpy":
            raise error
        return real_import(name, *args, **kwargs)

    return fake_import


def test_numpy_loads_on_this_machine() -> None:
    stream = io.StringIO()
    cpu.check_numpy(stream)
    assert stream.getvalue() == ""


def test_unsupported_cpu_explains_and_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(builtins, "__import__", _failing_import(RuntimeError(NUMPY_ERROR)))
    stream = io.StringIO()
    with pytest.raises(SystemExit) as exit_info:
        cpu.check_numpy(stream)
    assert exit_info.value.code == 1
    message = stream.getvalue()
    assert "x86-64-v2" in message
    assert '"host"' in message and "« host »" in message
    assert "docs/troubleshooting.md" in message and "docs/fr/troubleshooting.md" in message


def test_other_runtime_error_is_not_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(builtins, "__import__", _failing_import(RuntimeError("autre chose")))
    stream = io.StringIO()
    with pytest.raises(RuntimeError, match="autre chose"):
        cpu.check_numpy(stream)
    assert stream.getvalue() == ""
