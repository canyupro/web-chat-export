"""ExportPipeline 单元测试（纯逻辑，不联网）。

覆盖：
  - 管线与数据源解耦：任意鸭子类型 provider（只需 config/logger/fetch_all_chats）
    即可使用 export_by_date / export_all
  - 多数据源聚合 aggregate()：两平台合并、按日期分组、总 README、close 被调用
"""
import os
import sys
import tempfile
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from models import ExportConfig, ExportFormat, ChatSession, ChatMessage
from exporters.pipeline import ExportPipeline
from exporters.provider import ChatProvider


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
        print("导出管线（Provider/Pipeline）单元测试")
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


class FakeProvider(ChatProvider):
    """鸭子类型数据源：只实现契约，不依赖 BaseExporter。"""

    platform = "fake"

    def __init__(self, config, sessions, closed_flag=None):
        super().__init__(config)
        self._sessions = sessions
        self.closed = False
        self._closed_flag = closed_flag

    def check_auth(self):
        return True

    def fetch_all_chats(self):
        return self._sessions

    def close(self):
        self.closed = True
        if self._closed_flag is not None:
            self._closed_flag.append(self.platform)


def _make_session(sid: str, title: str, days_ago: int = 0) -> ChatSession:
    ts = int(datetime.now().timestamp()) - days_ago * 86400
    return ChatSession(
        id=sid, title=title, create_time=ts,
        messages=[ChatMessage(role="user", content=f"{title} 的消息")],
    )


@runner.test("管线与数据源解耦（FakeProvider + export_by_date）")
def test_pipeline_independent():
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    sessions = [
        _make_session("1", "今天会话", 0),
        _make_session("2", "昨天会话", 1),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        config = ExportConfig(platform="fake", engine="http", output_dir=tmp,
                              format=ExportFormat.MARKDOWN)
        provider = FakeProvider(config, sessions)
        pipeline = ExportPipeline(provider)
        result = pipeline.export_by_date(today)
        assert result.exported == 1, f"今天应导 1 条，实得 {result.exported}"
        date_dir = Path(tmp) / today
        files = [x for x in date_dir.glob("*.md") if x.name != "README.md"]
        assert len(files) == 1
        assert "今天会话" in files[0].read_text(encoding="utf-8")
        # 平台标记写入 README
        readme = (date_dir / "README.md").read_text(encoding="utf-8")
        assert "fake" in readme


@runner.test("管线 export_all 生成总 README")
def test_pipeline_export_all():
    sessions = [_make_session("1", "对话A", 0)]
    with tempfile.TemporaryDirectory() as tmp:
        config = ExportConfig(platform="fake", output_dir=tmp, format=ExportFormat.MARKDOWN)
        provider = FakeProvider(config, sessions)
        pipeline = ExportPipeline(provider)
        results = pipeline.export_all()
        assert len(results) == 1
        master = Path(tmp) / "README.md"
        assert master.exists()
        assert "按日期浏览" in master.read_text(encoding="utf-8")
        date_str = datetime.now().strftime("%Y-%m-%d")
        date_readme = Path(tmp) / date_str / "README.md"
        assert date_readme.exists()
        assert "对话A" in date_readme.read_text(encoding="utf-8")


@runner.test("聚合导出：两平台合并按日期分组 + 统一 close")
def test_aggregate():
    closed = []
    sessions_a = [
        _make_session("a1", "平台A今天", 0),
        _make_session("a2", "平台A昨天", 1),
    ]
    sessions_b = [_make_session("b1", "平台B今天", 0)]
    config_a = ExportConfig(platform="fake_a", output_dir="/tmp/ignored_a")
    config_b = ExportConfig(platform="fake_b", output_dir="/tmp/ignored_b")
    provider_a = FakeProvider(config_a, sessions_a, closed)
    provider_b = FakeProvider(config_b, sessions_b, closed)
    # 覆盖 platform，区分两个 provider（close 记录用）
    provider_a.platform = "fake_a"
    provider_b.platform = "fake_b"

    with tempfile.TemporaryDirectory() as tmp:
        results = ExportPipeline.aggregate([provider_a, provider_b], tmp)
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now().timestamp() - 86400)
        yesterday_str = datetime.fromtimestamp(yesterday).strftime("%Y-%m-%d")
        # 今天：A+B 两平台共 2 个会话；昨天：A 1 个
        today_dir = Path(tmp) / today
        files = [x for x in today_dir.glob("*.md") if x.name != "README.md"]
        assert len(files) == 2, f"今天应聚合 2 个会话文件，实得 {[x.name for x in files]}"
        yesterday_dir = Path(tmp) / yesterday_str
        yfiles = [x for x in yesterday_dir.glob("*.md") if x.name != "README.md"]
        assert len(yfiles) == 1, f"昨天应 1 个会话文件，实得 {[x.name for x in yfiles]}"
        # 总 README 覆盖两个日期
        master = (Path(tmp) / "README.md").read_text(encoding="utf-8")
        assert "按日期浏览" in master
        assert today in master and yesterday_str in master
        # 两个 provider 都调用了 close
        assert closed == ["fake_a", "fake_b"], f"close 应被调用，实得 {closed}"
        assert provider_a.closed and provider_b.closed


@runner.test("聚合导出：某平台拉取失败不阻塞其余平台")
def test_aggregate_partial_failure():
    closed = []
    sessions_a = [_make_session("a1", "平台A会话", 0)]

    class BrokenProvider(FakeProvider):
        platform = "fake_b"

        def fetch_all_chats(self):
            raise RuntimeError("模拟平台故障")

    config_a = ExportConfig(platform="fake_a", output_dir="/tmp/x")
    config_b = ExportConfig(platform="fake_b", output_dir="/tmp/y")
    provider_a = FakeProvider(config_a, sessions_a, closed)
    provider_a.platform = "fake_a"
    provider_b = BrokenProvider(config_b, [], closed)

    with tempfile.TemporaryDirectory() as tmp:
        results = ExportPipeline.aggregate([provider_a, provider_b], tmp)
        today = datetime.now().strftime("%Y-%m-%d")
        files = [x for x in (Path(tmp) / today).glob("*.md") if x.name != "README.md"]
        assert len(files) == 1
        assert closed == ["fake_a", "fake_b"]


if __name__ == "__main__":
    sys.exit(0 if runner.run() else 1)
