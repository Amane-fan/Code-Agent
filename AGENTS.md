# Repository Guidelines

## Project Structure & Module Organization

This is a Python 3.11 terminal code agent built with LangChain, LangGraph, and uv. Runtime code lives in `src/terminal_code_agent/`. Key modules include `graph.py` for the explicit LangGraph workflow, `tools.py` for model-exposed tools, `tool_gate.py` and `tool_runtime.py` for approval policy, and `schemas.py` for structured outputs. Tests live in `tests/` and cover path safety, graph routes, token budgets, and output schema validation. Architecture notes are in `docs/development.md`.

## Build, Test, and Development Commands

- `uv sync`: install and synchronize dependencies from `pyproject.toml` and `uv.lock`.
- `uv run terminal-code-agent --workdir .`: run the CLI against the current directory.
- `uv run python -m terminal_code_agent --workdir .`: run the same CLI via the module entry point.
- `uv run pytest`: run the full test suite configured in `pyproject.toml`.
- `uv run ruff check .`: run lint checks.
- `uv run mypy src`: run static type checks for source files.

Use uv for all dependency changes and commit the updated `uv.lock`.

## Coding Style & Naming Conventions

Follow Ruff settings in `pyproject.toml`: Python 3.11 target, 100-character line length, and lint rules `E`, `F`, `I`, `UP`, and `B`. Use 4-space indentation, snake_case for functions and modules, PascalCase for classes, and clear test names such as `test_rejects_path_escape`. Keep prompts in `prompts.py`, schemas in `schemas.py`, and all exposed tools in `tools.py` with `@tool`.

## Testing Guidelines

Tests use pytest and should avoid real external LLM calls; use mocks or direct node and route checks. Add or update tests when changing graph routing, tool approval, path validation, output repair, context compaction, or token budgeting. Name files `tests/test_<area>.py` and run `uv run pytest` before submitting.

## Commit & Pull Request Guidelines

Recent history uses concise Conventional Commit prefixes, for example `feat: implement terminal code agent`, `docs: 添加开发文档`, `refactor: 重构图结构`, and `chore: 忽略日志文件`. Keep commits focused and use `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, or `chore:`. Pull requests should include a summary, tests run, linked issues when relevant, and screenshots only for visual documentation or terminal-output changes.

## Security & Agent-Specific Constraints

Do not replace the explicit LangGraph structure with a black-box agent. File tools must stay confined to the startup `workdir`. `run_shell`, `write_file`, and `apply_patch` require human approval by default. Never log secrets, tokens, full `.env` contents, private keys, or credential files. Final agent responses produced by the application must remain valid `FinalAnswer` JSON.
