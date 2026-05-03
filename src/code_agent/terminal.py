from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.history import InMemoryHistory


class SlashCommandCompleter(Completer):
    """在输入开头补全内置斜杠命令。"""

    def __init__(self, commands: list[str]) -> None:
        self.commands = commands

    def get_completions(self, document: Document, complete_event: object) -> Iterator[Completion]:
        text = document.text_before_cursor
        if not text.startswith("/") or " " in text:
            return
        for command in self.commands:
            if command.startswith(text):
                yield Completion(command, start_position=-len(text))


_PROMPT_SESSION: PromptSession[str] | None = None


def enable_line_editing() -> None:
    """当平台支持时，启用基于 readline 的行编辑。"""

    try:
        import readline  # noqa: F401
    except ImportError:
        return


def read_prompt(prompt: str, *, commands: list[str] | None = None) -> str:
    """读取一行增强型终端输入，支持历史记录和斜杠命令补全。"""

    global _PROMPT_SESSION
    if _PROMPT_SESSION is None:
        _PROMPT_SESSION = PromptSession(
            completer=SlashCommandCompleter(commands or []),
            complete_while_typing=True,
            history=InMemoryHistory(),
        )
    with preserve_stdin_terminal():
        return _PROMPT_SESSION.prompt(prompt)


@contextmanager
def preserve_stdin_terminal() -> Iterator[None]:
    """在可能修改 stdin 终端设置的代码执行后恢复原设置。"""

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
