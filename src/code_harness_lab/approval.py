from __future__ import annotations

from dataclasses import dataclass
from typing import TextIO

from .types import PatchProposal


def _display_text(text: str) -> str:
    return "".join(
        character if character.isprintable() or character in "\n\t" else f"\\u{ord(character):04x}"
        for character in text
    )


class DenyAll:
    def approve_patch(self, proposal: PatchProposal) -> bool:
        return False

    def answer(self, question: str) -> str | None:
        return None


@dataclass(slots=True)
class TerminalApproval:
    input_stream: TextIO
    output_stream: TextIO

    def approve_patch(self, proposal: PatchProposal) -> bool:
        print(f"\nProposed patch to {proposal.path}:\n{_display_text(proposal.diff)}", file=self.output_stream)
        print("Type 'approve' to apply it (anything else denies): ", end="", file=self.output_stream, flush=True)
        return self.input_stream.readline().rstrip("\r\n") == "approve"

    def answer(self, question: str) -> str | None:
        print(f"\nQuestion from the model: {_display_text(question)}", file=self.output_stream)
        print("Answer (empty input denies): ", end="", file=self.output_stream, flush=True)
        answer = self.input_stream.readline().rstrip("\r\n")
        return answer or None
