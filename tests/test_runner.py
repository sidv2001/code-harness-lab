from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path

import pytest

from code_harness_lab.demo import BROKEN_SOURCE, FIXED_SOURCE
from code_harness_lab.approval import TerminalApproval
from code_harness_lab.model import FakeModel, ScriptExhausted
from code_harness_lab.runner import Runner
from code_harness_lab.trace import JsonlTrace
from code_harness_lab.types import (
    AskHuman,
    Finish,
    ListFiles,
    ObservationStatus,
    PatchProposal,
    ProposePatch,
    ReadFile,
    RunConfig,
    RunStatus,
    TestResult as SandboxTestResult,
    TestSandbox as SandboxProtocol,
    TestStatus as SandboxTestStatus,
    ToolRequest,
)
from code_harness_lab.workspace import Workspace


@dataclass
class DecisionGate:
    approve: bool
    answer_text: str | None = None
    proposals: list[PatchProposal] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)

    def approve_patch(self, proposal: PatchProposal) -> bool:
        self.proposals.append(proposal)
        return self.approve

    def answer(self, question: str) -> str | None:
        self.questions.append(question)
        return self.answer_text


@dataclass
class StubSandbox:
    response: SandboxTestResult
    calls: int = 0

    def run_tests(self, workspace: Path) -> SandboxTestResult:
        self.calls += 1
        return self.response


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "calculator.py").write_text(BROKEN_SOURCE, encoding="utf-8")
    return Workspace(root, frozenset({"calculator.py"}))


def run_script(
    workspace: Workspace,
    tmp_path: Path,
    script: tuple[ToolRequest, ...],
    *,
    gate: DecisionGate | None = None,
    sandbox: SandboxProtocol | None = None,
    config: RunConfig | None = None,
    trace_name: str = "run.jsonl",
):
    model = FakeModel(script)
    trace_path = tmp_path / trace_name
    with JsonlTrace(trace_path) as trace:
        result = Runner(workspace, model, trace, approval_gate=gate, sandbox=sandbox, config=config).run("Fix addition")
    return result, model, trace_path


def events(trace_path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]


def test_policy_denies_traversal_and_keeps_trace_out_of_context(workspace: Workspace, tmp_path: Path) -> None:
    outside = tmp_path / "private.txt"
    outside.write_text("should never be observed", encoding="utf-8")
    result, model, trace_path = run_script(
        workspace,
        tmp_path,
        (
            ListFiles(".."),
            ReadFile("../private.txt"),
            ReadFile("../run.jsonl"),
            ProposePatch("../private.txt", "should never be observed", "oops"),
            Finish("Fixed"),
        ),
    )

    assert result.status is RunStatus.UNCHANGED
    assert outside.read_text(encoding="utf-8") == "should never be observed"
    assert all(context.latest.status is ObservationStatus.DENIED for context in model.seen_contexts[1:])
    assert all("should never be observed" not in (context.latest.text if context.latest else "") for context in model.seen_contexts)
    assert events(trace_path)[-1]["status"] == "unchanged"


def test_denied_patch_never_writes_or_calls_sandbox(workspace: Workspace, tmp_path: Path) -> None:
    sandbox = StubSandbox(SandboxTestResult(SandboxTestStatus.PASSED, "stub only"))
    result, model, trace_path = run_script(
        workspace,
        tmp_path,
        (ProposePatch("calculator.py", BROKEN_SOURCE, FIXED_SOURCE), Finish("This is not proof")),
        sandbox=sandbox,
    )

    assert result.status is RunStatus.UNCHANGED
    assert workspace.read_text("calculator.py") == BROKEN_SOURCE
    assert sandbox.calls == 0
    assert model.seen_contexts[1].latest.status is ObservationStatus.DENIED
    assert "Human approval" in model.seen_contexts[1].latest.text
    assert not any(event["event"] == "patch_applied" for event in events(trace_path))


def test_non_boolean_approval_does_not_apply_patch(workspace: Workspace, tmp_path: Path) -> None:
    class InvalidGate(DecisionGate):
        def approve_patch(self, proposal: PatchProposal) -> bool:
            self.proposals.append(proposal)
            return "approve"  # type: ignore[return-value]

    result, _, _ = run_script(
        workspace,
        tmp_path,
        (ProposePatch("calculator.py", BROKEN_SOURCE, FIXED_SOURCE), Finish("Done")),
        gate=InvalidGate(approve=True),
    )
    assert result.status is RunStatus.UNCHANGED
    assert workspace.read_text("calculator.py") == BROKEN_SOURCE


def test_approved_patch_is_unverified_without_sandbox(workspace: Workspace, tmp_path: Path) -> None:
    gate = DecisionGate(approve=True)
    result, model, trace_path = run_script(
        workspace,
        tmp_path,
        (
            ListFiles(),
            ReadFile("calculator.py"),
            ProposePatch("calculator.py", BROKEN_SOURCE, FIXED_SOURCE),
            Finish("I proposed a patch"),
        ),
        gate=gate,
    )

    assert result.status is RunStatus.UNVERIFIED
    assert result.changed_files == ("calculator.py",)
    assert (result.turns, result.cost_units) == (4, 4)
    assert workspace.read_text("calculator.py") == FIXED_SOURCE
    assert gate.proposals[0].diff.startswith("--- a/calculator.py\n+++ b/calculator.py\n")
    assert model.seen_contexts[-1].latest.status is ObservationStatus.NOT_RUN
    assert "NOT RUN" in model.seen_contexts[-1].latest.text
    assert [event["event"] for event in events(trace_path)].count("patch_applied") == 1
    assert os.stat(trace_path).st_mode & 0o777 == 0o600


def test_observation_and_ledger_stay_bounded(workspace: Workspace, tmp_path: Path) -> None:
    (workspace.root / "calculator.py").write_text("x" * 800, encoding="utf-8")
    config = RunConfig(max_observation_chars=64, max_ledger_entries=2, max_ledger_summary_chars=24)
    result, model, trace_path = run_script(
        workspace,
        tmp_path,
        (ReadFile("calculator.py"),) * 4 + (Finish("End"),),
        config=config,
    )

    assert result.status is RunStatus.UNCHANGED
    assert model.seen_contexts[0].latest is None
    assert model.seen_contexts[1].latest.text.endswith("[truncated]")
    assert all(
        (context.latest is None or len(context.latest.text) <= 64)
        and len(context.ledger) <= 2
        and all(len(entry.summary) <= 24 for entry in context.ledger)
        for context in model.seen_contexts
    )
    assert len([event for event in events(trace_path) if event["event"] == "tool_step"]) == 5
    assert len(model.seen_contexts[-1].ledger) == 2


@pytest.mark.parametrize(
    ("config", "calls", "cost"),
    [
        (RunConfig(max_turns=2, max_cost_units=20), 2, 2),
        (RunConfig(max_turns=5, max_cost_units=3, cost_per_call=2), 1, 2),
        (RunConfig(max_turns=5, max_cost_units=1, cost_per_call=2), 0, 0),
    ],
)
def test_turn_and_cost_limits_stop_before_extra_model_call(
    workspace: Workspace, tmp_path: Path, config: RunConfig, calls: int, cost: int
) -> None:
    result, model, trace_path = run_script(
        workspace, tmp_path, (ListFiles(), ListFiles(), Finish("Done")), config=config
    )

    assert result.status is RunStatus.BUDGET_EXHAUSTED
    assert (result.turns, result.cost_units) == (calls, cost)
    assert len(model.seen_contexts) == calls
    assert events(trace_path)[-1]["status"] == "budget_exhausted"


def test_script_exhaustion_is_an_error_not_a_success(workspace: Workspace, tmp_path: Path) -> None:
    with JsonlTrace(tmp_path / "incomplete.jsonl") as trace:
        runner = Runner(workspace, FakeModel((ListFiles(),)), trace)
        with pytest.raises(ScriptExhausted, match="explicit Finish"):
            runner.run("Fix addition")
    assert events(tmp_path / "incomplete.jsonl")[-1]["event"] == "model_call_reserved"


def test_restart_requires_fresh_trace_and_fresh_approval(workspace: Workspace, tmp_path: Path) -> None:
    first_path = tmp_path / "first.jsonl"
    with JsonlTrace(first_path) as trace:
        first_model = FakeModel((ProposePatch("calculator.py", BROKEN_SOURCE, FIXED_SOURCE), Finish("Done")))
        first_runner = Runner(workspace, first_model, trace, approval_gate=DecisionGate(approve=True))
        assert first_runner.run("Fix addition").status is RunStatus.UNVERIFIED
        with pytest.raises(RuntimeError, match="cannot be restarted"):
            first_runner.run("Fix addition")
    original_trace = first_path.read_bytes()

    with pytest.raises(FileExistsError):
        JsonlTrace(first_path)
    second, second_model, _ = run_script(
        workspace,
        tmp_path,
        (ProposePatch("calculator.py", FIXED_SOURCE, BROKEN_SOURCE), Finish("Done")),
        trace_name="second.jsonl",
    )
    assert second.status is RunStatus.UNCHANGED
    assert workspace.read_text("calculator.py") == FIXED_SOURCE
    assert second_model.seen_contexts[0].ledger == ()
    assert second_model.seen_contexts[0].latest is None
    assert first_path.read_bytes() == original_trace


def test_symlink_and_hardlink_are_not_read_or_patched(workspace: Workspace, tmp_path: Path) -> None:
    outside = tmp_path / "outside.py"
    outside.write_text("outside content", encoding="utf-8")
    allowed = workspace.root / "calculator.py"
    allowed.unlink()

    allowed.symlink_to(outside)
    symlink_result, symlink_model, _ = run_script(
        workspace,
        tmp_path,
        (ReadFile("calculator.py"), ProposePatch("calculator.py", "outside content", "altered"), Finish("Done")),
        gate=DecisionGate(approve=True),
        trace_name="symlink.jsonl",
    )
    assert symlink_result.status is RunStatus.UNCHANGED
    assert symlink_model.seen_contexts[1].latest.status is ObservationStatus.DENIED
    assert outside.read_text(encoding="utf-8") == "outside content"

    allowed.unlink()
    os.link(outside, allowed)
    hardlink_result, hardlink_model, _ = run_script(
        workspace, tmp_path, (ReadFile("calculator.py"), Finish("Done")), trace_name="hardlink.jsonl"
    )
    assert hardlink_result.status is RunStatus.UNCHANGED
    assert hardlink_model.seen_contexts[1].latest.status is ObservationStatus.DENIED
    assert outside.read_text(encoding="utf-8") == "outside content"


def test_stale_patch_after_approval_does_not_overwrite(workspace: Workspace, tmp_path: Path) -> None:
    class EditingGate(DecisionGate):
        def approve_patch(self, proposal: PatchProposal) -> bool:
            (workspace.root / proposal.path).write_text("another edit\n", encoding="utf-8")
            return super().approve_patch(proposal)

    gate = EditingGate(approve=True)
    sandbox = StubSandbox(SandboxTestResult(SandboxTestStatus.PASSED, "stub only"))
    result, model, trace_path = run_script(
        workspace,
        tmp_path,
        (ProposePatch("calculator.py", BROKEN_SOURCE, FIXED_SOURCE), Finish("Done")),
        gate=gate,
        sandbox=sandbox,
    )
    assert result.status is RunStatus.UNCHANGED
    assert model.seen_contexts[1].latest.status is ObservationStatus.DENIED
    assert "changed during approval" in model.seen_contexts[1].latest.text
    assert workspace.read_text("calculator.py") == "another edit\n"
    assert sandbox.calls == 0
    assert not any(event["event"] == "patch_applied" for event in events(trace_path))


def test_ask_human_bounds_answers_and_does_not_grant_patch_approval(workspace: Workspace, tmp_path: Path) -> None:
    gate = DecisionGate(approve=False, answer_text="Inspect the arithmetic")
    result, model, _ = run_script(
        workspace,
        tmp_path,
        (AskHuman("What should I inspect?"), ProposePatch("calculator.py", BROKEN_SOURCE, FIXED_SOURCE), Finish("Done")),
        gate=gate,
    )
    assert result.status is RunStatus.UNCHANGED
    assert model.seen_contexts[1].latest.text == "Inspect the arithmetic"
    assert model.seen_contexts[2].latest.status is ObservationStatus.DENIED
    assert workspace.read_text("calculator.py") == BROKEN_SOURCE
    assert gate.questions == ["What should I inspect?"]

    too_long = DecisionGate(approve=False, answer_text="x" * 300)
    _, bounded_model, _ = run_script(
        workspace,
        tmp_path,
        (AskHuman("Any guidance?"), Finish("Done")),
        gate=too_long,
        config=RunConfig(max_answer_chars=20),
        trace_name="bounded-answer.jsonl",
    )
    assert bounded_model.seen_contexts[1].latest.status is ObservationStatus.DENIED
    assert "Answer exceeds" in bounded_model.seen_contexts[1].latest.text


@pytest.mark.parametrize(
    ("test_status", "run_status"),
    [(SandboxTestStatus.PASSED, RunStatus.VERIFIED), (SandboxTestStatus.FAILED, RunStatus.TESTS_FAILED)],
)
def test_trusted_sandbox_adapter_result_is_distinct_from_model_note(
    workspace: Workspace, tmp_path: Path, test_status: SandboxTestStatus, run_status: RunStatus
) -> None:
    sandbox = StubSandbox(SandboxTestResult(test_status, "test-only adapter"))
    result, _, _ = run_script(
        workspace,
        tmp_path,
        (ProposePatch("calculator.py", BROKEN_SOURCE, FIXED_SOURCE), Finish("I claim success")),
        gate=DecisionGate(approve=True),
        sandbox=sandbox,
    )
    assert sandbox.calls == 1
    assert result.status is run_status
    assert result.final_note == "I claim success"


def test_malformed_sandbox_result_cannot_become_verified(workspace: Workspace, tmp_path: Path) -> None:
    class MalformedSandbox:
        def run_tests(self, workspace: Path) -> SandboxTestResult:
            return {"status": "passed"}  # type: ignore[return-value]

    with pytest.raises(TypeError, match="typed TestResult"):
        SandboxTestResult("passed", "not a typed status")  # type: ignore[arg-type]
    with JsonlTrace(tmp_path / "bad-sandbox.jsonl") as trace:
        runner = Runner(
            workspace,
            FakeModel((ProposePatch("calculator.py", BROKEN_SOURCE, FIXED_SOURCE), Finish("Done"))),
            trace,
            approval_gate=DecisionGate(approve=True),
            sandbox=MalformedSandbox(),
        )
        with pytest.raises(TypeError, match="typed TestResult"):
            runner.run("Fix addition")
    assert events(tmp_path / "bad-sandbox.jsonl")[-1]["event"] == "patch_applied"


def test_trace_inside_workspace_is_rejected(workspace: Workspace) -> None:
    with JsonlTrace(workspace.root / "trace.jsonl") as trace:
        with pytest.raises(ValueError, match="outside"):
            Runner(workspace, FakeModel((Finish("Done"),)), trace)


@pytest.mark.parametrize("bad_content", [b"x" * 4097, b"\xff"])
def test_oversize_or_non_utf8_file_is_denied(workspace: Workspace, tmp_path: Path, bad_content: bytes) -> None:
    (workspace.root / "calculator.py").write_bytes(bad_content)
    result, model, _ = run_script(workspace, tmp_path, (ReadFile("calculator.py"), Finish("Done")))
    assert result.status is RunStatus.UNCHANGED
    assert model.seen_contexts[1].latest.status is ObservationStatus.DENIED


def test_terminal_controls_cannot_hide_patch_or_question(workspace: Workspace, tmp_path: Path) -> None:
    result, model, _ = run_script(
        workspace,
        tmp_path,
        (ProposePatch("calculator.py", BROKEN_SOURCE, FIXED_SOURCE + "\x1b[2J"), Finish("Done")),
        gate=DecisionGate(approve=True),
    )
    assert result.status is RunStatus.UNCHANGED
    assert model.seen_contexts[1].latest.status is ObservationStatus.DENIED
    assert workspace.read_text("calculator.py") == BROKEN_SOURCE

    output = StringIO()
    gate = TerminalApproval(StringIO("\n"), output)
    assert gate.answer("Question\x1b[2J") is None
    assert "\\u001b" in output.getvalue()
    assert "\x1b" not in output.getvalue()


def test_allowlist_rejects_hidden_and_nested_names(workspace: Workspace) -> None:
    for invalid in (".git", "../outside", "has\nnewline"):
        with pytest.raises(ValueError, match="visible allowlisted basename"):
            Workspace(workspace.root, frozenset({invalid}))
    with pytest.raises(ValueError, match="exactly one"):
        Workspace(workspace.root, frozenset({"calculator.py", "other.py"}))


def test_objective_limit_is_checked_before_start(workspace: Workspace, tmp_path: Path) -> None:
    with JsonlTrace(tmp_path / "no-start.jsonl") as trace:
        runner = Runner(workspace, FakeModel((Finish("Done"),)), trace, config=RunConfig(max_objective_chars=10))
        with pytest.raises(ValueError, match="Objective exceeds"):
            runner.run("a" * 11)
    assert (tmp_path / "no-start.jsonl").read_text(encoding="utf-8") == ""
