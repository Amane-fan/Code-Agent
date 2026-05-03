from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

from code_agent.models import AgentRun, ModelCallUsage


@dataclass
class SessionStore:
    """把同一终端会话内的多轮 Agent 运行保存到同一个本地 JSON。"""

    session_dir: Path
    session_path: Path | None = None
    runs: list[AgentRun] = field(default_factory=list)
    model_calls: list[ModelCallUsage] = field(default_factory=list)
    _system_instructions_recorded: bool = False

    def save(self, run: AgentRun) -> Path:
        self.session_dir.mkdir(parents=True, exist_ok=True)
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        saved_model_calls = self._prepare_model_calls(run.model_calls)
        saved_run = replace(run, session_path=path, model_calls=saved_model_calls)
        self.runs.append(saved_run)
        self.model_calls.extend(saved_run.model_calls)
        self._write(path)
        return path

    def append_model_calls(self, model_calls: list[ModelCallUsage]) -> Path:
        self.session_dir.mkdir(parents=True, exist_ok=True)
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.model_calls.extend(self._prepare_model_calls(model_calls))
        self._write(path)
        return path

    def _prepare_model_calls(self, model_calls: list[ModelCallUsage]) -> list[ModelCallUsage]:
        prepared: list[ModelCallUsage] = []
        for model_call in model_calls:
            if not model_call.system_instructions:
                prepared.append(model_call)
                continue
            if self._system_instructions_recorded:
                prepared.append(replace(model_call, system_instructions=""))
                continue
            self._system_instructions_recorded = True
            prepared.append(model_call)
        return prepared

    def _path(self) -> Path:
        if self.session_path is None:
            # 使用 UTC 时间戳保证文件名稳定且易排序。
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            self.session_path = self.session_dir / "sessions" / f"{timestamp}.json"
        return self.session_path

    def _write(self, path: Path) -> None:
        # 顶层保留最近一轮的 AgentRun 结构，runs 保存同一会话内的完整多轮日志。
        data = self.runs[-1].to_json_dict() if self.runs else {}
        data["runs"] = [item.to_json_dict() for item in self.runs]
        data["model_calls"] = [asdict(item) for item in self.model_calls]
        data["session_path"] = str(path)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
