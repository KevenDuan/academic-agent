from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.agent.agent_loop import AgentLoop
from app.agent.registry import SkillContext, SkillRegistry
from app.agent.skills import default_skills_dir
from app.core.session_store import SessionStore


class FakeRag:
    def __init__(self):
        self.searched = []

    def list_papers(self):
        return [SimpleNamespace(paper_id="p1", title="Test Paper", block_count=2)]

    def search(self, query, top_k=5):
        self.searched.append((query, top_k))
        return []

    def format_context(self, results):
        return ""

    def paper_evidence(self, identifier, max_chars=24000):
        return f"evidence for {identifier}"


class FakeTranslator:
    def translate_text(self, text):
        return f"译文：{text}"


class FakeCompletions:
    def __init__(self):
        self.calls = []
        self.responses = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class FakeClient:
    def __init__(self):
        self.completions = FakeCompletions()
        self.chat = SimpleNamespace(completions=self.completions)


def response(content=None, tool_calls=None):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content, tool_calls=tool_calls)
            )
        ]
    )


def tool_call(call_id, name, arguments):
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


class P4Tests(unittest.TestCase):
    def test_default_registry_loads_all_v1_skills(self):
        registry = SkillRegistry(default_skills_dir())
        self.assertEqual(
            set(registry.skills),
            {
                "search_papers",
                "get_paper_summary",
                "extract_key_points",
                "translate_text",
                "web_search",
            },
        )
        self.assertTrue(all("function" in schema for schema in registry.schemas()))

    def test_registry_loads_new_skill_without_core_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "echo"
            folder.mkdir()
            (folder / "SKILL.md").write_text(
                """---\nname: echo\ndescription: Echo text\nparameters:\n  type: object\n  properties:\n    text: {type: string}\n  required: [text]\n---\n""",
                encoding="utf-8",
            )
            (folder / "skill.py").write_text(
                "def run(args, context):\n    return args['text']\n",
                encoding="utf-8",
            )
            registry = SkillRegistry(directory)
            self.assertEqual(
                registry.execute("echo", {"text": "hello"}, SkillContext(None, None)),
                "hello",
            )

    def test_agent_loop_executes_tool_then_returns_final_answer(self):
        client = FakeClient()
        client.completions.responses = [
            response(
                tool_calls=[
                    tool_call("call-1", "search_papers", '{"query":"segmentation"}')
                ]
            ),
            response("基于检索结果，论文讨论了分割方法。[来源1]"),
        ]
        rag = FakeRag()
        loop = AgentLoop(
            client,
            "test-model",
            SkillRegistry(default_skills_dir()),
            rag,
            FakeTranslator(),
        )
        result = loop.answer([], "")
        self.assertEqual(result.answer, "基于检索结果，论文讨论了分割方法。[来源1]")
        self.assertEqual([trace.name for trace in result.tool_traces], ["search_papers"])
        self.assertEqual(rag.searched, [("segmentation", 5)])
        self.assertEqual(len(client.completions.calls), 2)
        self.assertEqual(client.completions.calls[1]["messages"][-1]["role"], "tool")

    def test_tool_failure_is_returned_to_model_and_loop_continues(self):
        client = FakeClient()
        client.completions.responses = [
            response(tool_calls=[tool_call("call-1", "missing_tool", "{}")]),
            response("我无法使用该工具，但仍可以继续回答。"),
        ]
        loop = AgentLoop(
            client,
            "test-model",
            SkillRegistry(default_skills_dir()),
            FakeRag(),
            FakeTranslator(),
        )
        result = loop.answer([], "")
        self.assertIn("无法使用该工具", result.answer)
        self.assertIn("工具执行失败", result.tool_traces[0].result)

    def test_malformed_tool_arguments_do_not_break_loop(self):
        client = FakeClient()
        client.completions.responses = [
            response(tool_calls=[tool_call("call-1", "search_papers", "not-json")]),
            response("参数有误，未执行工具。"),
        ]
        loop = AgentLoop(
            client,
            "test-model",
            SkillRegistry(default_skills_dir()),
            FakeRag(),
            FakeTranslator(),
        )
        result = loop.answer([], "")
        self.assertEqual(result.answer, "参数有误，未执行工具。")
        self.assertEqual(result.tool_traces[0].arguments, {})

    def test_tool_calls_can_be_persisted_as_session_messages(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(Path(directory) / "sessions.db")
            try:
                session = store.create_session()
                store.add_message(
                    session.session_id,
                    "tool",
                    "evidence",
                    tool_calls={"name": "search_papers", "arguments": {"query": "x"}},
                )
                message = store.get_messages(session.session_id)[0]
                self.assertEqual(message.role, "tool")
                self.assertEqual(message.tool_calls["name"], "search_papers")
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
