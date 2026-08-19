"""多平台导出器单元测试（纯逻辑，不联网）。

覆盖：
  - 工厂/引擎默认选择
  - DeepSeek 消息解析（fragments 结构）
  - ChatGPT 消息解析（mapping 结构）
  - 千问浏览器收割的消息解析（content_block 结构）
  - 豆包浏览器收割的消息解析
  - Grok responses 解析
  - 导出管线（按日期分组 + 渲染）
"""
import os
import sys
import tempfile
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from models import ExportConfig, ExportFormat, ChatSession, ChatMessage
from exporters import build_exporter, default_engine


class TestRunner:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.tests = []

    def test(self, name):
        def decorator(func):
            self.tests.append((name, func))
            return func
        return decorator

    def run(self):
        print("=" * 60)
        print("多平台导出器单元测试")
        print("=" * 60)
        for name, func in self.tests:
            try:
                func()
                print(f"[测试] {name}... ✓ 通过")
                self.passed += 1
            except AssertionError as e:
                print(f"[测试] {name}... ✗ 失败: {e}")
                self.failed += 1
            except Exception as e:
                print(f"[测试] {name}... ✗ 错误: {e}")
                self.failed += 1
        print()
        print("=" * 60)
        print(f"测试结果: {self.passed} 通过, {self.failed} 失败")
        return self.failed == 0


runner = TestRunner()


@runner.test("引擎默认选择")
def test_default_engine():
    assert default_engine("deepseek") == "http"
    assert default_engine("chatgpt") == "http"
    assert default_engine("qwen") == "browser"
    assert default_engine("doubao") == "browser"
    assert default_engine("grok") == "browser"


@runner.test("工厂构建")
def test_factory():
    cases = [
        ("deepseek", "http", "DeepSeekHttpExporter"),
        ("chatgpt", "http", "ChatGPTHttpExporter"),
        ("qwen", "browser", "QwenBrowserExporter"),
        ("doubao", "browser", "DoubaoBrowserExporter"),
        ("grok", "browser", "GrokBrowserExporter"),
    ]
    for platform, engine, cls in cases:
        exp = build_exporter(ExportConfig(platform=platform, engine=engine))
        assert type(exp).__name__ == cls, f"{platform}/{engine} 期望 {cls} 实得 {type(exp).__name__}"


@runner.test("DeepSeek fragments 消息解析")
def test_deepseek_parse():
    from exporters.deepseek import DeepSeekHttpExporter
    exp = DeepSeekHttpExporter(ExportConfig(cookie="x", engine="http"))
    messages_data = [
        {"role": "user", "inserted_at": 100, "fragments": [
            {"type": "REQUEST", "content": "你好"}]},
        {"role": "assistant", "inserted_at": 200, "fragments": [
            {"type": "RESPONSE", "content": "你好！"},
            {"type": "THINK", "content": "思考中..."},
            {"type": "TOOL_SEARCH", "content": "搜索"}]},
    ]
    msgs = exp.parse_messages(messages_data)
    assert len(msgs) == 2
    assert msgs[0].role == "user" and msgs[0].content == "你好"
    assert msgs[1].role == "assistant" and msgs[1].content == "你好！"


@runner.test("ChatGPT mapping 消息解析")
def test_chatgpt_parse():
    from exporters.chatgpt import ChatGPTHttpExporter
    exp = ChatGPTHttpExporter(ExportConfig(platform="chatgpt", engine="http"))
    detail = {
        "mapping": {
            "n1": {"message": {"author": {"role": "user"},
                               "content": {"parts": ["提问1"]},
                               "create_time": 100}},
            "n2": {"message": {"author": {"role": "assistant"},
                               "content": {"parts": ["回答1"]},
                               "create_time": 200}},
        }
    }
    msgs = exp.parse_messages(detail)
    assert len(msgs) == 2
    assert msgs[0].role == "user" and msgs[0].content == "提问1"
    assert msgs[1].role == "assistant" and msgs[1].content == "回答1"

    # ISO 时间转秒
    assert exp._iso_to_ts("2026-08-17T05:55:44.370119Z") is not None


@runner.test("千问 content_block 消息解析")
def test_qwen_parse():
    from exporters.qwen import QwenBrowserExporter
    # API 响应监听范式：msg/list 真实结构（每条=一轮：request/response_messages）
    msg_items = [
        # 欢迎轮（request 是 hidden，跳过；response 是助手欢迎语）
        {"request_messages": [{"content": "", "mime_type": "text/hidden"}],
         "response_messages": [{"content": "Hi，我是千问。", "mime_type": "multi_load/iframe"}],
         "request_timestamp": 1786857931, "response_timestamp": 1786857932},
        # 正常一轮
        {"request_messages": [{"content": "用户问题", "mime_type": "text/plain"}],
         "response_messages": [{"content": "助手回答", "mime_type": "text/plain"}],
         "request_timestamp": 1786857940, "response_timestamp": 1786857941},
        # 只有用户消息的一轮
        {"request_messages": [{"content": "只有提问", "mime_type": "text/plain"}],
         "response_messages": [], "request_timestamp": 1786857950},
    ]
    msgs = QwenBrowserExporter._parse_api_messages(msg_items)
    assert len(msgs) == 4, f"应 4 条，实得 {len(msgs)}"
    assert msgs[0].role == "assistant" and "千问" in msgs[0].content
    assert msgs[1].role == "user" and msgs[1].content == "用户问题"
    assert msgs[2].role == "assistant" and msgs[2].content == "助手回答"
    assert msgs[3].role == "user" and msgs[3].content == "只有提问"


@runner.test("豆包 content_block 消息解析")
def test_doubao_parse():
    from exporters.doubao import DoubaoBrowserExporter
    msg_list = [
        {"sender": "123", "user_type": "1", "content_type": "text", "create_time": "100",
         "content_block": [{"content": {"text_block": {"text": "用户问题"}}}]},
        {"sender": "456", "user_type": "2", "content_type": "text", "create_time": "200",
         "content_block": [{"content": {"text_block": {"text": "助手回答"}}}]},
    ]
    msgs = DoubaoBrowserExporter._parse_messages(msg_list)
    assert len(msgs) == 2
    assert msgs[0].role == "user" and msgs[0].content == "用户问题"
    assert msgs[1].role == "assistant" and msgs[1].content == "助手回答"


@runner.test("Grok responses 解析")
def test_grok_parse():
    from exporters.grok import GrokBrowserExporter
    responses = [
        {"sender": "human", "message": "用户问题",
         "createTime": "2026-08-17T05:55:44.370119Z"},
        {"sender": "ASSISTANT", "message": "助手回答",
         "createTime": "2026-08-17T05:56:00Z"},
        {"sender": "human", "message": "第二个问题"},
        {"sender": "assistant", "message": "第二个回答"},
    ]
    msgs = GrokBrowserExporter._parse_responses(responses)
    assert len(msgs) == 4
    assert msgs[0].role == "user" and msgs[0].content == "用户问题"
    assert msgs[1].role == "assistant" and msgs[1].content == "助手回答"
    assert msgs[2].role == "user"
    assert msgs[3].role == "assistant"


@runner.test("导出管线按日期分组")
def test_export_pipeline():
    """用一个内存假导出器验证按日期分组+导出"""
    from exporters.base import BaseExporter

    class FakeExporter(BaseExporter):
        platform = "fake"

        def __init__(self, config, sessions):
            super().__init__(config)
            self._sessions = sessions

        def check_auth(self):
            return True

        def fetch_all_chats(self):
            return self._sessions

    # 构造两个会话，昨天 + 今天
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    sessions = [
        ChatSession(id="1", title="今天对话", create_time=int(now.timestamp()),
                    messages=[ChatMessage(role="user", content="hi")]),
        ChatSession(id="2", title="昨天对话",
                    create_time=int(now.timestamp()) - 86400,
                    messages=[ChatMessage(role="user", content="旧消息")]),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        config = ExportConfig(platform="fake", engine="http", output_dir=tmp,
                              format=ExportFormat.MARKDOWN)
        exp = FakeExporter(config, sessions)
        result = exp.export_by_date(today)
        assert result.exported == 1, f"今天应导 1 条，实得 {result.exported}"
        # 文件存在（对话文件以 序号_ 开头，排除 README.md）
        f = Path(tmp) / today
        assert f.exists()
        files = list(f.glob("*.md"))
        chat_files = [x for x in files if x.name != "README.md"]
        assert len(chat_files) == 1, f"今天应导出 1 个对话文件，实得 {[x.name for x in chat_files]}"
        assert "今天对话" in chat_files[0].read_text(encoding="utf-8")


@runner.test("导出 all 生成总 README")
def test_export_all():
    from exporters.base import BaseExporter

    class FakeExporter(BaseExporter):
        platform = "fake"

        def __init__(self, config, sessions):
            super().__init__(config)
            self._sessions = sessions

        def check_auth(self):
            return True

        def fetch_all_chats(self):
            return self._sessions

    now = datetime.now()
    sessions = [
        ChatSession(id="1", title="对话A", create_time=int(now.timestamp()),
                    messages=[ChatMessage(role="user", content="a")]),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        config = ExportConfig(platform="fake", output_dir=tmp, format=ExportFormat.MARKDOWN)
        exp = FakeExporter(config, sessions)
        results = exp.export_all()
        assert len(results) == 1
        # 总 README（日期级索引，含日期链接）
        readme = Path(tmp) / "README.md"
        assert readme.exists()
        assert "按日期浏览" in readme.read_text(encoding="utf-8")
        # 会话标题在日期文件夹 README 里
        date_str = now.strftime("%Y-%m-%d")
        date_readme = Path(tmp) / date_str / "README.md"
        assert date_readme.exists()
        assert "对话A" in date_readme.read_text(encoding="utf-8")


if __name__ == "__main__":
    sys.exit(0 if runner.run() else 1)
