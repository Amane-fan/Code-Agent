from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any


def enable_line_editing() -> None:
    """Enable readline-backed editing when the platform provides it."""

    try:
        import readline  # noqa: F401
    except ImportError:
        return


@contextmanager
def preserve_stdin_terminal() -> Iterator[None]:
    """Restore stdin terminal settings after code that may change them."""

    attrs: Any | None = None
    fd: int | None = None
    try:
        if sys.stdin.isatty():
            import termios

            fd = sys.stdin.fileno()
            attrs = termios.tcgetattr(fd)
    except (ImportError, OSError, ValueError):
        attrs = None
        fd = None

    try:
        yield
    finally:
        if attrs is None or fd is None:
            return
        try:
            import termios

            termios.tcsetattr(fd, termios.TCSADRAIN, attrs)
        except (ImportError, OSError, ValueError):
            return
