from __future__ import annotations

from pathlib import Path
from typing import NoReturn


class SandboxUnavailable(RuntimeError):
    """No isolated runner exists for candidate code."""


class UnavailableSandbox:
    def run_tests(self, workspace: Path) -> NoReturn:
        raise SandboxUnavailable("No isolated test executor is configured; candidate code was NOT RUN")
