from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TextIO


class JsonlTrace:
    def __init__(self, path: Path) -> None:
        if not hasattr(os, "O_NOFOLLOW"):
            raise RuntimeError("This starter needs POSIX O_NOFOLLOW for local file safety")
        self.path = path
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND | os.O_NOFOLLOW
        descriptor = os.open(path, flags, 0o600)
        self._file: TextIO = os.fdopen(descriptor, "w", encoding="utf-8", newline="\n")

    def append(self, event: str, **fields: object) -> None:
        record = {"event": event, **fields}
        self._file.write(json.dumps(record, sort_keys=True, ensure_ascii=True) + "\n")
        self._file.flush()
        os.fsync(self._file.fileno())

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> JsonlTrace:
        return self

    def __exit__(self, exception_type: object, exception: object, traceback: object) -> None:
        self.close()
