"""BaseExporter：数据源 + 导出能力的组合壳。

职责拆分：
- 数据源契约（check_auth / fetch_all_chats）由 ChatProvider 定义，BaseExporter 继承；
- 导出管线（按日期分组、md/json/html 渲染、README）由 ExportPipeline 实现，
  BaseExporter 在 __init__ 内嵌一个 pipeline 并委托全部 export_* 方法。

子类（HTTP/浏览器引擎 + 各平台适配器）只需实现 check_auth / fetch_all_chats，
导出能力完全复用。此壳保留旧类名与方法，向后兼容既有调用方。
"""
import logging
import sys
from pathlib import Path
from typing import List, Optional

from models import ChatSession, ExportResult
from exporters.provider import ChatProvider
from exporters.pipeline import ExportPipeline
from exporters.formatter import safe_filename


class BaseExporter(ChatProvider):
    """所有平台/引擎导出器的基类（数据源 + 导出管线组合）。"""

    platform: str = "base"

    def __init__(self, config):
        super().__init__(config)
        self.output_dir = Path(config.output_dir).resolve()
        self.logger = self._setup_logger()
        self._pipeline = ExportPipeline(self)

    def _setup_logger(self) -> logging.Logger:
        logger = logging.getLogger(f"{self.platform.title()}Exporter")
        logger.setLevel(logging.INFO)
        logger.handlers.clear()
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s", datefmt="%H:%M:%S")
        )
        logger.addHandler(handler)
        return logger

    def _safe_filename(self, name: str, max_length: int = 80) -> str:
        return safe_filename(name, max_length)

    # ------------------------------------------------------------------
    # 数据源契约（子类实现）
    # ------------------------------------------------------------------
    def check_auth(self) -> bool:
        raise NotImplementedError

    def fetch_all_chats(self) -> List[ChatSession]:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # 导出管线（委托 ExportPipeline）
    # ------------------------------------------------------------------
    def export_session(self, session, output_path) -> bool:
        return self._pipeline.export_session(session, output_path)

    def export_by_date(self, target_date: Optional[str] = None) -> ExportResult:
        return self._pipeline.export_by_date(target_date)

    def export_all(self) -> List[ExportResult]:
        return self._pipeline.export_all()
