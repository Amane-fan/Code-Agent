# Repository Guidelines

## Project Structure & Module Organization

This is a Python 3.12 project using a `src/` layout. Core package code lives in `src/code_agent/`, with CLI entry points in `cli.py` and `__main__.py`. Orchestration, providers, sessions, prompts, and security checks are split across modules such as `react.py`, `providers.py`, `session.py`, and `security.py`. Built-in tools live in `src/code_agent/tools/`; prompt templates live in `src/code_agent/prompts/`.

Tests are in `tests/`; documentation is in `docs/`; local skill examples are under `skills/`. Runtime directories such as `.venv/`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`, `.code-agent/`, and `workspace/` are not source.

## Build, Test, and Development Commands

- `uv sync` installs runtime dependencies from `pyproject.toml` and `uv.lock`.
- `uv sync --extra dev` installs `pytest`, `ruff`, and `mypy`.
- `uv run python -m code_agent --workspace . --provider offline --no-session` runs a local smoke test without external model calls.
- `uv run pytest` runs tests configured for `tests/`.
- `uv run ruff check .` runs lint checks with the project’s Ruff settings.
- `uv run mypy src` runs strict type checking for package code.
- `uv run code-agent-mcp-server` starts the MCP example server; use `uv run code-agent-mcp-client list-tools` to inspect it.

## Coding Style & Naming Conventions

Use 4-space indentation, type hints, and small modules with clear ownership. Ruff targets Python 3.12 with a 100-character line length. Mypy runs in `strict` mode, so public functions need precise parameter and return types.

Use `snake_case` for modules, functions, variables, and tests; use `PascalCase` for classes. Keep CLI commands, tool names, and environment variables stable and documented.

## Testing Guidelines

Prefer focused `pytest` tests near the changed behavior. Name files `tests/test_<feature>.py` and functions `test_<expected_behavior>()`. For provider or CLI changes, include offline-provider coverage. Run `uv run pytest` before submitting; add `ruff` and `mypy` for typed package changes.

## Commit & Pull Request Guidelines

Recent history uses short, prefix-based commits such as `feat: ...` and `optimize: ...`. Keep prefixes lowercase when possible and describe the change, for example `feat: add session token accounting`.

Pull requests should include a concise description, rationale, tests run, and any security or configuration impact. Link issues when available. Add screenshots or terminal excerpts only for CLI UX changes.

## Security & Configuration Tips

Do not commit `.env` or credentials. Keep `.env.example` updated when configuration keys change. Preserve workspace isolation: file and shell tools must stay bounded to the explicit workspace, avoid sensitive paths, and require confirmation for shell execution. Update `docs/security.md` when guarantees change.
