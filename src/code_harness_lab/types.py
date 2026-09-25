from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol, TypeAlias


@dataclass(frozen=True, slots=True)
class ListFiles:
    path: str = "."


@dataclass(frozen=True, slots=True)
class ReadFile:
    path: str


@dataclass(frozen=True, slots=True)
class ProposePatch:
    path: str
    expected_text: str
    replacement_text: str


@dataclass(frozen=True, slots=True)
class AskHuman:
    question: str


@dataclass(frozen=True, slots=True)
class Finish:
    note: str


ToolRequest: TypeAlias = ListFiles | ReadFile | ProposePatch | AskHuman | Finish


class ObservationStatus(StrEnum):
    OK = "ok"
    DENIED = "denied"
    ERROR = "error"
    NOT_RUN = "not_run"


class RunStatus(StrEnum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    TESTS_FAILED = "tests_failed"
    UNCHANGED = "unchanged"
    BUDGET_EXHAUSTED = "budget_exhausted"


class TestStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ToolObservation:
    tool: str
    status: ObservationStatus
    text: str


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    tool: str
    status: ObservationStatus
    summary: str


@dataclass(frozen=True, slots=True)
class ModelContext:
    objective: str
    latest: ToolObservation | None
    ledger: tuple[LedgerEntry, ...]
    remaining_turns: int
    remaining_cost_units: int


@dataclass(frozen=True, slots=True)
class PatchProposal:
    path: str
    expected_text: str
    replacement_text: str
    diff: str


@dataclass(frozen=True, slots=True)
class TestResult:
    status: TestStatus
    detail: str

    def __post_init__(self) -> None:
        if not isinstance(self.status, TestStatus) or not isinstance(self.detail, str) or not self.detail.strip():
            raise TypeError("A sandbox must return a typed TestResult with a nonempty detail")


@dataclass(frozen=True, slots=True)
class RunResult:
    status: RunStatus
    turns: int
    cost_units: int
    changed_files: tuple[str, ...]
    final_note: str | None
    latest: ToolObservation | None
    trace_path: Path


@dataclass(frozen=True, slots=True)
class RunConfig:
    max_turns: int = 5
    max_cost_units: int = 5
    cost_per_call: int = 1
    max_objective_chars: int = 240
    max_observation_chars: int = 640
    max_ledger_entries: int = 3
    max_ledger_summary_chars: int = 96
    max_question_chars: int = 240
    max_answer_chars: int = 240
    max_finish_chars: int = 360

    def __post_init__(self) -> None:
        positive = (
            "max_turns",
            "max_cost_units",
            "cost_per_call",
            "max_objective_chars",
            "max_question_chars",
            "max_answer_chars",
            "max_finish_chars",
        )
        for name in positive:
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.max_observation_chars < 32 or self.max_ledger_summary_chars < 16:
            raise ValueError("Observation and ledger limits are too small to report truncation")
        if self.max_ledger_entries < 0:
            raise ValueError("max_ledger_entries cannot be negative")


class Model(Protocol):
    def next_request(self, context: ModelContext) -> ToolRequest: ...


class ApprovalGate(Protocol):
    def approve_patch(self, proposal: PatchProposal) -> bool: ...

    def answer(self, question: str) -> str | None: ...


class TestSandbox(Protocol):
    def run_tests(self, workspace: Path) -> TestResult: ...
