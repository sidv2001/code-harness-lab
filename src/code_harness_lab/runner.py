from __future__ import annotations

from collections import deque
from dataclasses import asdict

from .approval import DenyAll
from .sandbox import SandboxUnavailable, UnavailableSandbox
from .trace import JsonlTrace
from .types import (
    ApprovalGate,
    AskHuman,
    Finish,
    LedgerEntry,
    ListFiles,
    Model,
    ModelContext,
    ObservationStatus,
    ProposePatch,
    ReadFile,
    RunConfig,
    RunResult,
    RunStatus,
    TestResult,
    TestSandbox,
    TestStatus,
    ToolObservation,
    ToolRequest,
)
from .workspace import PolicyViolation, Workspace


class Runner:
    def __init__(
        self,
        workspace: Workspace,
        model: Model,
        trace: JsonlTrace,
        approval_gate: ApprovalGate | None = None,
        sandbox: TestSandbox | None = None,
        config: RunConfig | None = None,
    ) -> None:
        self.workspace = workspace
        self.model = model
        self.trace = trace
        self.approval_gate = approval_gate if approval_gate is not None else DenyAll()
        self.sandbox = sandbox if sandbox is not None else UnavailableSandbox()
        self.config = config if config is not None else RunConfig()
        if trace.path.resolve(strict=True).is_relative_to(workspace.root):
            raise ValueError("The append-only trace must be outside the model-visible workspace")
        self._started = False
        self._changed_files: set[str] = set()
        self._last_test_result: TestResult | None = None

    def run(self, objective: str) -> RunResult:
        if self._started:
            raise RuntimeError("Runs cannot be restarted or resumed; create a fresh trace and runner")
        if not isinstance(objective, str) or not objective.strip():
            raise ValueError("A nonempty text objective is required")
        if len(objective) > self.config.max_objective_chars:
            raise ValueError("Objective exceeds the model-context character limit")
        self._started = True
        self.trace.append(
            "run_started",
            objective=objective,
            allowed_files=sorted(self.workspace.allowed_files),
            limits=asdict(self.config),
        )
        latest: ToolObservation | None = None
        ledger: deque[LedgerEntry] = deque(maxlen=self.config.max_ledger_entries)
        turns = 0
        cost_units = 0

        while turns < self.config.max_turns and cost_units + self.config.cost_per_call <= self.config.max_cost_units:
            context = ModelContext(
                objective=objective,
                latest=latest,
                ledger=tuple(ledger),
                remaining_turns=self.config.max_turns - turns,
                remaining_cost_units=self.config.max_cost_units - cost_units,
            )
            cost_units += self.config.cost_per_call
            self.trace.append("model_call_reserved", turn=turns + 1, cost_units=cost_units)
            request = self.model.next_request(context)
            if not isinstance(request, (ListFiles, ReadFile, ProposePatch, AskHuman, Finish)):
                raise TypeError(f"Model returned an unsupported request: {type(request).__name__}")

            observation = self._dispatch(request)
            latest = ToolObservation(
                observation.tool,
                observation.status,
                self._clip(observation.text, self.config.max_observation_chars),
            )
            turns += 1
            self.trace.append(
                "tool_step",
                turn=turns,
                request={"tool": latest.tool, "input": asdict(request)},
                observation={"status": latest.status.value, "text": latest.text},
            )
            ledger.append(
                LedgerEntry(
                    latest.tool,
                    latest.status,
                    self._clip(latest.text.replace("\n", " "), self.config.max_ledger_summary_chars),
                )
            )
            if isinstance(request, Finish) and latest.status is ObservationStatus.OK:
                return self._end(self._finished_status(), turns, cost_units, request.note, latest)

        return self._end(RunStatus.BUDGET_EXHAUSTED, turns, cost_units, None, latest)

    def _dispatch(self, request: ToolRequest) -> ToolObservation:
        if isinstance(request, ListFiles):
            try:
                files = self.workspace.list_files(request.path)
            except PolicyViolation as error:
                return ToolObservation("list", ObservationStatus.DENIED, str(error))
            return ToolObservation("list", ObservationStatus.OK, "\n".join(files) or "No allowlisted files")

        if isinstance(request, ReadFile):
            try:
                content = self.workspace.read_text(request.path)
            except PolicyViolation as error:
                return ToolObservation("read", ObservationStatus.DENIED, str(error))
            except FileNotFoundError:
                return ToolObservation("read", ObservationStatus.ERROR, "Allowlisted file is missing")
            return ToolObservation("read", ObservationStatus.OK, content)

        if isinstance(request, ProposePatch):
            try:
                proposal = self.workspace.preflight_patch(
                    request.path, request.expected_text, request.replacement_text
                )
            except PolicyViolation as error:
                return ToolObservation("propose_patch", ObservationStatus.DENIED, str(error))
            except FileNotFoundError:
                return ToolObservation("propose_patch", ObservationStatus.ERROR, "Allowlisted file is missing")
            if self.approval_gate.approve_patch(proposal) is not True:
                return ToolObservation(
                    "propose_patch", ObservationStatus.DENIED, "Human approval was not granted; nothing was written"
                )
            try:
                self.workspace.apply_patch(proposal)
            except PolicyViolation as error:
                return ToolObservation("propose_patch", ObservationStatus.DENIED, str(error))
            self._changed_files.add(proposal.path)
            self._last_test_result = None
            self.trace.append("patch_applied", path=proposal.path)
            try:
                self._last_test_result = self.sandbox.run_tests(self.workspace.root)
            except SandboxUnavailable as error:
                return ToolObservation("propose_patch", ObservationStatus.NOT_RUN, f"Patch applied; {error}")
            if not isinstance(self._last_test_result, TestResult):
                raise TypeError("A sandbox must return a typed TestResult")
            if self._last_test_result.status is TestStatus.FAILED:
                return ToolObservation(
                    "propose_patch",
                    ObservationStatus.ERROR,
                    f"Patch applied; isolated tests failed: {self._last_test_result.detail}",
                )
            if self._last_test_result.status is TestStatus.PASSED:
                return ToolObservation(
                    "propose_patch",
                    ObservationStatus.OK,
                    f"Patch applied; isolated tests passed: {self._last_test_result.detail}",
                )
            raise TypeError("A sandbox returned an unsupported test status")

        if isinstance(request, AskHuman):
            if len(request.question) > self.config.max_question_chars:
                return ToolObservation("ask_human", ObservationStatus.DENIED, "Question exceeds the character limit")
            answer = self.approval_gate.answer(request.question)
            if answer is None:
                return ToolObservation("ask_human", ObservationStatus.DENIED, "No human answer was provided")
            if len(answer) > self.config.max_answer_chars:
                return ToolObservation("ask_human", ObservationStatus.DENIED, "Answer exceeds the character limit")
            return ToolObservation("ask_human", ObservationStatus.OK, answer)

        if len(request.note) > self.config.max_finish_chars:
            return ToolObservation("finish", ObservationStatus.DENIED, "Finish note exceeds the character limit")
        return ToolObservation("finish", ObservationStatus.OK, "Model requested an end to the run; this is not proof of correctness")

    def _finished_status(self) -> RunStatus:
        if not self._changed_files:
            return RunStatus.UNCHANGED
        if self._last_test_result is None:
            return RunStatus.UNVERIFIED
        if self._last_test_result.status is TestStatus.FAILED:
            return RunStatus.TESTS_FAILED
        if self._last_test_result.status is TestStatus.PASSED:
            return RunStatus.VERIFIED
        raise TypeError("A sandbox returned an unsupported test status")

    def _end(
        self, status: RunStatus, turns: int, cost_units: int, final_note: str | None, latest: ToolObservation | None
    ) -> RunResult:
        result = RunResult(
            status=status,
            turns=turns,
            cost_units=cost_units,
            changed_files=tuple(sorted(self._changed_files)),
            final_note=final_note,
            latest=latest,
            trace_path=self.trace.path,
        )
        self.trace.append(
            "run_ended",
            status=status.value,
            turns=turns,
            cost_units=cost_units,
            changed_files=result.changed_files,
            final_note=final_note,
        )
        return result

    @staticmethod
    def _clip(text: str, limit: int) -> str:
        marker = " [truncated]"
        return text if len(text) <= limit else text[: limit - len(marker)] + marker
