from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from code_agent.models import AgentRun


@dataclass(frozen=True)
class SessionStore:
    """把每次 Agent 运行保存为本地 JSON，便于复盘和调试。"""

    session_dir: Path

    def save(self, run: AgentRun) -> Path:
        self.session_dir.mkdir(parents=True, exist_ok=True)
        # 使用 UTC 时间戳保证文件名稳定且易排序。
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = self.session_dir / "sessions" / f"{timestamp}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = run.to_json_dict()
        data["session_path"] = str(path)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return path
