from __future__ import annotations

from dataclasses import dataclass, field

from .types import ModelContext, ToolRequest


class ScriptExhausted(RuntimeError):
    """The deterministic script ended without an explicit finish request."""


@dataclass(slots=True)
class FakeModel:
    script: tuple[ToolRequest, ...]
    seen_contexts: list[ModelContext] = field(default_factory=list, init=False)
    _position: int = field(default=0, init=False, repr=False)

    def next_request(self, context: ModelContext) -> ToolRequest:
        if self._position >= len(self.script):
            raise ScriptExhausted("FakeModel needs an explicit Finish step")
        self.seen_contexts.append(context)
        request = self.script[self._position]
        self._position += 1
        return request
