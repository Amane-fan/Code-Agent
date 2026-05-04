import json

import pytest
from pydantic import ValidationError

from terminal_code_agent.schemas import FinalAnswer, parse_final_answer


def test_final_answer_accepts_valid_json() -> None:
    parsed = parse_final_answer(
        json.dumps(
            {
                "type": "final",
                "answer": "已完成。",
                "summary": "运行了测试。",
                "changed_files": [],
                "commands_run": ["uv run pytest"],
                "risks_or_notes": [],
                "next_steps": [],
            },
            ensure_ascii=False,
        )
    )

    assert parsed.type == "final"
    assert parsed.answer == "已完成。"


def test_final_answer_rejects_invalid_type() -> None:
    with pytest.raises(ValidationError):
        FinalAnswer.model_validate({"type": "message", "answer": "no"})
