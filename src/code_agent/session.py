from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

from code_agent.models import AgentRun


@dataclass
class SessionStore:
    """把同一终端会话内的多轮 Agent 运行保存到同一个本地 JSON。"""

    session_dir: Path
    session_path: Path | None = None
    runs: list[AgentRun] = field(default_factory=list)

    def save(self, run: AgentRun) -> Path:
        self.session_dir.mkdir(parents=True, exist_ok=True)
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        saved_run = replace(run, session_path=path)
        self.runs.append(saved_run)
        # 顶层保留最近一轮的 AgentRun 结构，runs 保存同一会话内的完整多轮日志。
        data = saved_run.to_json_dict()
        data["runs"] = [item.to_json_dict() for item in self.runs]
        data["session_path"] = str(path)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def _path(self) -> Path:
        if self.session_path is None:
            # 使用 UTC 时间戳保证文件名稳定且易排序。
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            self.session_path = self.session_dir / "sessions" / f"{timestamp}.json"
        return self.session_path
