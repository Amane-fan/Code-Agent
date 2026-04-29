from __future__ import annotations

import os
from pathlib import Path


def load_env_file(path: Path, *, override: bool = False) -> None:
    """加载简单的 .env 文件。

    为了避免额外依赖，这里只支持常见的 KEY=VALUE、注释和可选引号格式；
    已存在的系统环境变量默认不会被覆盖，便于 CI 或命令行临时配置优先。
    """

    if not path.exists():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return

    for line in lines:
        parsed = _parse_env_line(line)
        if parsed is None:
            continue
        key, value = parsed
        if override or key not in os.environ:
            os.environ[key] = value


def get_env(*names: str, default: str = "") -> str:
    """按优先级读取多个环境变量名，返回第一个非空值。"""

    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


def _parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped.removeprefix("export ").strip()
    if "=" not in stripped:
        return None
    key, value = stripped.split("=", 1)
    key = key.strip()
    if not key:
        return None
    return key, _strip_quotes(value.strip())


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value
