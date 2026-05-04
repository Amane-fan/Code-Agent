from terminal_code_agent.token_budget import compute_token_budget, estimate_tokens


def test_compute_token_budget() -> None:
    assert compute_token_budget(128000, 4096, 0.85) == 105318


def test_estimate_tokens_returns_positive_count_for_chinese() -> None:
    assert estimate_tokens("你好，终端 code agent") > 0
