from __future__ import annotations

import difflib
import errno
import os
import re
import stat
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .types import PatchProposal


class PolicyViolation(ValueError):
    """A file or patch is outside the starter's allowlisted scope."""


class StalePatch(PolicyViolation):
    """The file changed since the proposed base was read."""


@dataclass(frozen=True, slots=True)
class Workspace:
    root: Path
    allowed_files: frozenset[str]
    max_file_bytes: int = 4096
    max_diff_chars: int = 8192

    def __post_init__(self) -> None:
        if not hasattr(os, "O_NOFOLLOW"):
            raise RuntimeError("This starter needs POSIX O_NOFOLLOW for local file safety")
        if self.root.is_symlink() or not self.root.is_dir():
            raise ValueError("Workspace root must be an existing, non-symlink directory")
        object.__setattr__(self, "root", self.root.resolve(strict=True))
        object.__setattr__(self, "allowed_files", frozenset(self.allowed_files))
        if len(self.allowed_files) != 1 or any(
            not isinstance(name, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name) is None
            for name in self.allowed_files
        ):
            raise ValueError("The starter needs exactly one plain, visible allowlisted basename")
        if self.max_file_bytes <= 0 or self.max_diff_chars <= 0:
            raise ValueError("File and diff limits must be positive")

    def list_files(self, path: str) -> tuple[str, ...]:
        if path != ".":
            raise PolicyViolation("Only the allowlisted workspace root may be listed")
        with os.scandir(self.root) as entries:
            return tuple(
                sorted(
                    entry.name
                    for entry in entries
                    if entry.name in self.allowed_files
                    and entry.is_file(follow_symlinks=False)
                    and entry.stat(follow_symlinks=False).st_nlink == 1
                )
            )

    def read_text(self, path: str) -> str:
        text, _ = self._read_checked(path)
        return text

    def preflight_patch(self, path: str, expected_text: str, replacement_text: str) -> PatchProposal:
        self._checked_bytes(expected_text)
        self._checked_bytes(replacement_text)
        current = self.read_text(path)
        if current != expected_text:
            raise StalePatch("Patch base does not match the current file; nothing was written")
        if expected_text == replacement_text:
            raise PolicyViolation("No-op patches are not accepted")
        diff = "".join(
            difflib.unified_diff(
                expected_text.splitlines(keepends=True),
                replacement_text.splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
            )
        )
        if len(diff) > self.max_diff_chars:
            raise PolicyViolation("Proposed diff exceeds the display limit")
        return PatchProposal(path, expected_text, replacement_text, diff)

    def apply_patch(self, proposal: PatchProposal) -> None:
        replacement = self._checked_bytes(proposal.replacement_text)
        current, before_stat = self._read_checked(proposal.path)
        if current != proposal.expected_text:
            raise StalePatch("File changed during approval; nothing was written")

        descriptor, temporary_path = tempfile.mkstemp(prefix=".patch-", dir=self.root)
        try:
            with os.fdopen(descriptor, "wb") as temporary:
                temporary.write(replacement)
                temporary.flush()
                os.fsync(temporary.fileno())
            target = self.root / proposal.path
            now = os.lstat(target)
            if (
                now.st_dev,
                now.st_ino,
                now.st_size,
                now.st_mtime_ns,
            ) != (
                before_stat.st_dev,
                before_stat.st_ino,
                before_stat.st_size,
                before_stat.st_mtime_ns,
            ) or not stat.S_ISREG(now.st_mode):
                raise StalePatch("File changed while staging the patch; nothing was written")
            os.replace(temporary_path, target)
        finally:
            if os.path.exists(temporary_path):
                os.unlink(temporary_path)

    def _read_checked(self, path: str) -> tuple[str, os.stat_result]:
        if path not in self.allowed_files:
            raise PolicyViolation(f"Path is not on the file allowlist: {path!r}")
        try:
            descriptor = os.open(self.root / path, os.O_RDONLY | os.O_NOFOLLOW)
        except OSError as error:
            if error.errno == errno.ELOOP:
                raise PolicyViolation("Symlinked files are not allowed") from error
            raise
        with os.fdopen(descriptor, "rb") as file:
            details = os.fstat(file.fileno())
            if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
                raise PolicyViolation("Only regular, single-link files may be read or patched")
            if details.st_size > self.max_file_bytes:
                raise PolicyViolation("File exceeds the configured byte limit")
            data = file.read(self.max_file_bytes + 1)
            if len(data) > self.max_file_bytes:
                raise PolicyViolation("File exceeds the configured byte limit")
        try:
            return data.decode("utf-8"), details
        except UnicodeDecodeError as error:
            raise PolicyViolation("Only UTF-8 text files may be read or patched") from error

    def _checked_bytes(self, text: str) -> bytes:
        if not isinstance(text, str):
            raise PolicyViolation("Patches must contain UTF-8 text")
        try:
            data = text.encode("utf-8")
        except UnicodeEncodeError as error:
            raise PolicyViolation("Patches must contain valid UTF-8 text") from error
        if any(
            unicodedata.category(character) in {"Cc", "Cf"} and character not in "\n\t"
            for character in text
        ):
            raise PolicyViolation("Patch text contains terminal control or formatting characters")
        if len(data) > self.max_file_bytes:
            raise PolicyViolation("Patch text exceeds the configured byte limit")
        return data
