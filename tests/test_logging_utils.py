import json
import re

from terminal_code_agent.logging_utils import JsonlLogger


def test_jsonl_logger_uses_one_file_per_session(tmp_path) -> None:
    first = JsonlLogger(tmp_path)
    second = JsonlLogger(tmp_path)

    assert first.path != second.path
    assert re.fullmatch(r"agent-\d{8}-\d{6}-\d{6}-[0-9a-f]{8}\.jsonl", first.path.name)
    assert re.fullmatch(r"agent-\d{8}-\d{6}-\d{6}-[0-9a-f]{8}\.jsonl", second.path.name)


def test_jsonl_logger_reuses_session_file_for_events(tmp_path) -> None:
    logger = JsonlLogger(tmp_path)

    logger.event("run_start")
    logger.event("final_answer")

    records = [
        json.loads(line) for line in logger.path.read_text(encoding="utf-8").splitlines()
    ]
    assert [record["event"] for record in records] == ["run_start", "final_answer"]
    assert {record["session_id"] for record in records} == {logger.session_id}
