# Terminal Code Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the terminal code agent described in `docs/development.md`.

**Architecture:** Implement a `terminal_code_agent` package with focused modules for config, schemas, state, safe tool runtime, LangChain tools, gating, prompts, LLM setup, token budgeting, JSONL logs, LangGraph nodes, and CLI approval flow. The graph is explicit and uses the route fields defined in the development document.

**Tech Stack:** Python 3.11+, LangChain, LangGraph, Pydantic, pydantic-settings, python-dotenv, tiktoken, rich, uv, pytest, ruff.

---

### Task 1: Project Configuration

**Files:**
- Modify: `pyproject.toml`
- Modify: `.python-version`
- Modify: `.env.example`
- Create: `AGENTS.md`

- [ ] Update package metadata to `terminal-code-agent`, Python `>=3.11`, script `terminal-code-agent = "terminal_code_agent.cli:main"`, and docs-required dependencies.
- [ ] Set `.python-version` to `3.11`.
- [ ] Replace `.env.example` with the model and agent settings from `docs/development.md`.
- [ ] Add `AGENTS.md` with the long-term constraints from section 25.
- [ ] Run `uv sync` and update `uv.lock`.

### Task 2: Core Types And Helpers

**Files:**
- Create: `src/terminal_code_agent/__init__.py`
- Create: `src/terminal_code_agent/__main__.py`
- Create: `src/terminal_code_agent/config.py`
- Create: `src/terminal_code_agent/schemas.py`
- Create: `src/terminal_code_agent/state.py`
- Create: `src/terminal_code_agent/token_budget.py`
- Create: `src/terminal_code_agent/logging_utils.py`

- [ ] Implement `Settings` with `.env` support.
- [ ] Implement `FinalAnswer`, `ToolResult`, `PendingToolCall`, `SkillSelection`, `ApprovalRequest`, `ApprovalResume`.
- [ ] Implement `AgentState` and `ChatRecord` with append reducers for list fields.
- [ ] Implement token budget calculation and conservative token estimation.
- [ ] Implement JSONL logging with recursive redaction and text truncation.

### Task 3: Safe Tool Runtime And Tools

**Files:**
- Create: `src/terminal_code_agent/tool_runtime.py`
- Create: `src/terminal_code_agent/tools.py`
- Create: `src/terminal_code_agent/tool_gate.py`

- [ ] Implement `resolve_in_root()`, sensitive path matching, JSON result helpers, binary detection, output truncation, patch path validation, shell danger detection, and safe subprocess execution.
- [ ] Implement all eight `@tool` functions in `tools.py`: `list_files`, `search_files`, `grep`, `read_file`, `apply_patch`, `write_file`, `run_shell`, `load_skill_resource`.
- [ ] Keep all tool functions in `tools.py`; only helper functions live in `tool_runtime.py`.
- [ ] Implement risk classification and `evaluate_tool_calls()` in `tool_gate.py`.

### Task 4: Prompts, LLM, Graph, CLI

**Files:**
- Create: `src/terminal_code_agent/prompts.py`
- Create: `src/terminal_code_agent/llm.py`
- Create: `src/terminal_code_agent/graph.py`
- Create: `src/terminal_code_agent/cli.py`

- [ ] Define all prompt templates in `prompts.py`.
- [ ] Initialize the model with LangChain `init_chat_model()` and `.env` settings.
- [ ] Implement every LangGraph node and route from section 7.
- [ ] Use `interrupt()` for `human_approval`.
- [ ] Implement CLI argument parsing, interactive loop, approval y/n/edit handling, and final JSON printing.

### Task 5: Tests And Documentation

**Files:**
- Create: `tests/test_output_schema.py`
- Create: `tests/test_token_budget.py`
- Create: `tests/test_tools_path_safety.py`
- Create: `tests/test_tool_gate.py`
- Create: `tests/test_graph_routes.py`
- Create: `tests/test_cli_approval.py`
- Modify: `README.md`

- [ ] Add tests for schema validation and JSON parsing.
- [ ] Add tests for token budget and route behavior.
- [ ] Add tests for path safety, sensitive path denial, tools, dangerous shell denial, and skill resource escape denial.
- [ ] Add tests for tool gate routing and CLI approval parsing.
- [ ] Update README with installation, `.env`, usage, tools, approval, safety, logs, tests, and FAQ.
- [ ] Run `uv run pytest` and `uv run ruff check .`.

### Self-Review

The plan covers every completion standard in `docs/development.md` section 27. There are no TBD placeholders. Type names and file paths match the design and development document.
