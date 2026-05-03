# AGENTS.md — Code Agent Project Development Guide

## Project Overview

Code Agent is a terminal-first AI programming agent. It is built on the LangGraph ReAct tool loop and supports code reading, file modification, command execution, and multi-turn task collaboration. All file and shell capabilities are restricted to the directory boundary specified by `--workspace`, with an emphasis on auditability, controllability, and extensibility.

### Core Modules

| Module                  | Path                                             | Responsibility                                               |
| ----------------------- | ------------------------------------------------ | ------------------------------------------------------------ |
| CLI                     | `src/code_agent/cli.py`                          | Typer + prompt_toolkit + Rich interactive terminal           |
| Agent Facade            | `src/code_agent/agent.py`                        | Assembles dependencies and starts each task run              |
| LangGraph Runner        | `src/code_agent/react.py`                        | Drives model calls, tool execution, and limit protection via StateGraph |
| Provider Layer          | `src/code_agent/providers.py`                    | Wraps OpenAI-compatible chat models + offline mode           |
| Prompt Building         | `src/code_agent/prompting.py`                    | Dynamically combines system prompts, tool descriptions, and skill content |
| Conversation Management | `src/code_agent/conversation.py`                 | Multi-turn history, compressed summaries, and recent full turns |
| Context Assembly        | `src/code_agent/context.py`                      | Builds compressed input                                      |
| Tool Registration       | `src/code_agent/tools/`                          | Tool base class + automatic registration + default tool implementations |
| Skill System            | `src/code_agent/skills.py`                       | Skill metadata discovery, loading, and resource reading      |
| Skill Selection         | `src/code_agent/skill_selection.py`              | Automatically selects up to 3 relevant skills per turn       |
| Session Logging         | `src/code_agent/session.py`                      | JSON logs and token usage records                            |
| Security Module         | `src/code_agent/security.py`                     | Sensitive path filtering and secret redaction                |
| System Prompt           | `src/code_agent/prompts/system.md`               | Base system prompt template                                  |
| MCP Examples            | `src/code_agent/mcp_server.py` / `mcp_client.py` | MCP protocol validation                                      |

For detailed architecture, see `docs/architecture.md`.

---

## Development Environment

### Requirements

- **Python**: `>=3.12`
- **Package Manager**: [uv](https://docs.astral.sh/uv/)
- **Operating System**: Linux / macOS / WSL2

### Environment Variables

Configuration is read from the Code Agent project’s own `.env`, not from the target workspace’s `.env`:

```bash
API_KEY=your API key
BASE_URL=https://api.deepseek.com
MODEL=deepseek-v4-flash
```

### Running

```bash
# Start interactive mode
uv run python -m code_agent --workspace /path/to/target-project
```

---

## Technology Stack

### Runtime Dependencies

| Dependency              | Purpose                                                      |
| ----------------------- | ------------------------------------------------------------ |
| `langgraph>=1.1`        | Agent orchestration framework; StateGraph drives the ReAct loop |
| `langchain-openai>=1.1` | OpenAI-compatible chat model wrapper                         |
| `prompt_toolkit>=3.0`   | Interactive terminal input                                   |
| `rich>=13.7`            | Formatted terminal output and event stream rendering         |
| `typer>=0.12`           | CLI argument parsing                                         |
| `mcp>=1.0`              | MCP protocol example server/client                           |

### Development Dependencies

| Dependency    | Purpose                                                      |
| ------------- | ------------------------------------------------------------ |
| `pytest>=8.0` | Testing framework                                            |
| `ruff>=0.6`   | Linting + formatting, with `line-length=100` and `target=py312` |
| `mypy>=1.11`  | Static type checking, strict mode                            |

### Build System

- **build-backend**: hatchling
- **wheel packages**: `src/code_agent`
- **Entry scripts**: `code-agent`, `code-agent-mcp-server`, `code-agent-mcp-client`

---

## Agent Orchestration Guidelines

### Prefer LangGraph

For agent orchestration logic involving **multi-step decision loops, conditional branches, tool routing, and state management**, prefer implementing it with `langgraph`.

### Skill Selection Flow

Before each task turn, run skill selection first as an independent model call. Select up to 3 relevant skills. The complete `SKILL.md` files of selected skills are injected into the main task system instructions. If selection fails, skip it and continue with the main task.

---

## Code Style

### English Comments

Comments in code should be written in **Chinese** and follow these principles:

- **Comments are required for**: non-obvious logic, implicit constraints, workarounds, easily misunderstood behavior, and security-related decisions.
- **Comments are optional for**: routine code where names already express intent, getters/setters, and standard-pattern calls.
- Comment style: use single-line `#` comments and avoid overly long multi-line docstrings.
- Comments should explain **WHY**, not **WHAT**. The code itself should explain what it does.

### Python Coding Standards

- Follow `ruff` rules, with `line-length=100` and `target-version=py312`.
- Enforce `mypy --strict` type annotations.
- Use `hatchling` for builds, with the package directory as `src/code_agent`.
- Public APIs must remain backward compatible. Private APIs may be refactored freely.

### Secure Coding

- File tools must skip sensitive paths such as `.env`, private keys, credential files, `.git`, `.venv`, and `node_modules`.
- Suspected secret values must be redacted before display or storage.
- `run_shell` must require user confirmation before every execution.
- Tool operations must not go outside the `--workspace` boundary.
- Code Agent’s own configuration, including `.env`, system prompts, and skills, must be strictly isolated from the target workspace. Do not read configuration files from the target workspace.

---

## Git Commit Guidelines

Use the concise `<type>: <description>` format. Prefer English for the description, and use lowercase English for `type`.

### Commit Types

| type       | Meaning                                                    |
| ---------- | ---------------------------------------------------------- |
| `feat`     | New feature                                                |
| `fix`      | Bug fix                                                    |
| `optimize` | Optimization or refactor without functional changes        |
| `docs`     | Documentation changes                                      |
| `test`     | Test-related changes                                       |
| `chore`    | Miscellaneous changes, such as build or dependency updates |

### Rules

- Keep commit messages concise and clear. One line is enough.
- Do not mix unrelated changes into a single commit.
- Do not commit files that are excluded by `.gitignore`, such as `.env`, `.code-agent/`, and `workspace/`.

---

## Prohibited Actions

1. **Do not introduce other orchestration frameworks**: Do not use LangChain LCEL chains, custom state machines, or similar alternatives to replace LangGraph for agent orchestration.
2. **Do not operate outside boundaries**: File tools and shell tools must not access paths outside the directory specified by `--workspace`.
3. **Do not automatically execute shell commands**: `run_shell` must receive user confirmation before every execution. This must not be bypassed.
4. **Do not read sensitive files**: `.env`, private keys, `.git`, `.venv`, `node_modules`, and similar files must not be read or written by file tools.
5. **Do not read target workspace configuration**: The target workspace’s `.env`, prompt files, and `SKILL.md` must not affect agent behavior.
6. **Do not output secrets**: API keys, tokens, passwords, and other sensitive values must be redacted in logs and terminal output.
7. **Do not hardcode values**: All configurable values, such as API URLs, model names, and paths, should come from environment variables or reasonable defaults.
8. **Do not commit sensitive files**: `.env`, `.code-agent/`, and session logs must not be committed to version control.
9. **Do not run destructive commands**: Commands such as `rm -rf`, `git reset --hard`, and `git push --force` must not be executed unless the user explicitly requests and confirms them.
10. **Do not look at the contents of TODO.md.**