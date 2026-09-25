from __future__ import annotations

import argparse
import sys
from pathlib import Path
from uuid import uuid4

from .approval import TerminalApproval
from .model import FakeModel
from .runner import Runner
from .trace import JsonlTrace
from .types import Finish, ListFiles, ProposePatch, ReadFile, RunStatus
from .workspace import Workspace

BROKEN_SOURCE = (
    "def add(left: int, right: int) -> int:\n"
    '    """Return the sum of two integers."""\n'
    "    return left - right\n"
)
FIXED_SOURCE = BROKEN_SOURCE.replace("return left - right", "return left + right")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a scripted, offline coding-harness demo")
    parser.add_argument(
        "--output",
        type=Path,
        help="New directory for the synthetic workspace and private JSONL trace (default: .code-harness-runs/<id>)",
    )
    args = parser.parse_args(argv)
    output = args.output if args.output is not None else Path.cwd() / ".code-harness-runs" / uuid4().hex
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    workspace_path = output / "workspace"
    workspace_path.mkdir(mode=0o700)
    (workspace_path / "calculator.py").write_text(BROKEN_SOURCE, encoding="utf-8")

    model = FakeModel(
        (
            ListFiles(),
            ReadFile("calculator.py"),
            ProposePatch("calculator.py", BROKEN_SOURCE, FIXED_SOURCE),
            Finish("I proposed a one-line change; the harness reports whether it was applied or verified."),
        )
    )
    workspace = Workspace(workspace_path, frozenset({"calculator.py"}))
    approval = TerminalApproval(sys.stdin, sys.stdout)
    with JsonlTrace(output / "trace.jsonl") as trace:
        result = Runner(workspace, model, trace, approval_gate=approval).run(
            "Inspect the synthetic addition bug and propose a one-file correction"
        )

    print(f"\nRun status: {result.status.value}")
    print(f"Model calls: {result.turns}; synthetic cost units: {result.cost_units}")
    print(f"Changed files: {', '.join(result.changed_files) if result.changed_files else 'none'}")
    print("Candidate-code tests: NOT RUN (no isolated sandbox is installed)")
    print(f"Workspace: {workspace_path.resolve()}")
    print(f"Append-only trace: {result.trace_path.resolve()}")
    return 2 if result.status is RunStatus.BUDGET_EXHAUSTED else 0
