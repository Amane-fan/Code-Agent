from __future__ import annotations

import unittest

from code_agent.mcp_client import parse_args, parse_arguments_json
from code_agent.mcp_server import code_agent_add, code_agent_echo, code_agent_word_count


class McpExampleToolTests(unittest.TestCase):
    def test_echo_returns_structured_message(self) -> None:
        result = code_agent_echo("hello")

        self.assertEqual(result, {"message": "hello", "characters": 5})

    def test_add_returns_structured_sum(self) -> None:
        result = code_agent_add(2, 3)

        self.assertEqual(result, {"a": 2, "b": 3, "result": 5})

    def test_word_count_returns_structured_counts(self) -> None:
        result = code_agent_word_count("hello world\nsecond line")

        self.assertEqual(
            result,
            {
                "characters": 23,
                "lines": 2,
                "words": 4,
            },
        )


class McpClientArgumentTests(unittest.TestCase):
    def test_parse_list_tools_command(self) -> None:
        args = parse_args(["--url", "http://127.0.0.1:8000/sse", "list-tools"])

        self.assertEqual(args.url, "http://127.0.0.1:8000/sse")
        self.assertEqual(args.command, "list-tools")

    def test_parse_call_command_with_json_arguments(self) -> None:
        args = parse_args(
            [
                "--url",
                "http://127.0.0.1:8000/sse",
                "call",
                "code_agent_add",
                "--arguments",
                '{"a":2,"b":3}',
            ]
        )

        self.assertEqual(args.command, "call")
        self.assertEqual(args.tool_name, "code_agent_add")
        self.assertEqual(parse_arguments_json(args.arguments), {"a": 2, "b": 3})

    def test_parse_arguments_rejects_non_object_json(self) -> None:
        with self.assertRaises(ValueError):
            parse_arguments_json("[1, 2, 3]")


if __name__ == "__main__":
    unittest.main()
