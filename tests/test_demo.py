from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from code_harness_lab.demo import BROKEN_SOURCE, FIXED_SOURCE, main


def test_fixture_matches_scripted_demo() -> None:
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "calculator.py"
    assert fixture.read_text(encoding="utf-8") == BROKEN_SOURCE
    assert "return left - right" in BROKEN_SOURCE
    assert "return left + right" in FIXED_SOURCE


@pytest.mark.parametrize(
    ("answer", "status", "expected_source"),
    [
        ("approve\n", "unverified", FIXED_SOURCE),
        ("", "unchanged", BROKEN_SOURCE),
    ],
)
def test_cli_demo_uses_explicit_approval_and_reports_no_tests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    answer: str, status: str, expected_source: str
) -> None:
    output = tmp_path / "demo"
    monkeypatch.setattr(sys, "stdin", io.StringIO(answer))
    assert main(["--output", str(output)]) == 0

    stdout = capsys.readouterr().out
    assert f"Run status: {status}" in stdout
    assert "Candidate-code tests: NOT RUN" in stdout
    assert (output / "workspace" / "calculator.py").read_text(encoding="utf-8") == expected_source
    trace_events = [
        json.loads(line) for line in (output / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert trace_events[-1]["status"] == status
    assert [event["event"] for event in trace_events].count("tool_step") == 4
    with pytest.raises(FileExistsError):
        main(["--output", str(output)])
