"""BaseExporter：平台无关的导出管线骨架。

子类只需实现三件事：
  - check_auth() -> bool         认证是否有效
  - fetch_all_chats() -> List[ChatSession]   全量会话（含消息）

导出管线（按日期分组、md/json/html 渲染、README）统一在此实现。
"""
import logging
import sys
import time
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

from models import ChatSession, ChatMessage, ExportResult, ExportConfig, ExportFormat
from exporters.formatter import (
    safe_filename,
    render_session,
    get_date_from_ts,
    generate_date_readme,
    generate_master_readme,
)


class BaseExporter:
    """所有平台/引擎导出器的基类"""

    platform: str = "base"

    def __init__(self, config: ExportConfig):
        self.config = config
        self.output_dir = Path(config.output_dir).resolve()
        self.logger = self._setup_logger()

    # ------------------------------------------------------------------
    # 子类必须实现
    # ------------------------------------------------------------------
    def check_auth(self) -> bool:
        raise NotImplementedError

    def fetch_all_chats(self) -> List[ChatSession]:
        """获取全部会话（含消息）。子类实现。"""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # 通用工具
    # ------------------------------------------------------------------
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
    # 导出管线（平台无关）
    # ------------------------------------------------------------------
    def export_session(self, session: ChatSession, output_path: Path) -> bool:
        """导出单个会话到文件"""
        try:
            content = render_session(session, self.config.format)
            output_path.write_text(content, encoding="utf-8")
            return True
        except Exception as e:
            self.logger.error(f"导出文件失败 {output_path}: {e}")
            return False

    def export_by_date(self, target_date: Optional[str] = None) -> ExportResult:
        """按日期导出全部会话中落在该日期的部分"""
        # 解析目标日期
        if target_date:
            try:
                target_dt = datetime.strptime(target_date, "%Y-%m-%d")
            except ValueError:
                return ExportResult(
                    success=False, date=target_date, exported=0,
                    error="日期格式错误，请使用 YYYY-MM-DD 格式",
                )
        else:
            target_dt = datetime.now()

        date_str = target_dt.strftime("%Y-%m-%d")
        date_folder = self.output_dir / date_str
        date_folder.mkdir(parents=True, exist_ok=True)
        self.logger.info(f"目标日期: {date_str}，输出目录: {date_folder}")

        all_sessions = self.fetch_all_chats()
        if not all_sessions:
            self.logger.warning("没有获取到任何对话")
            generate_date_readme(date_folder, date_str, [], self.config.format, self.platform)
            return ExportResult(success=True, date=date_str, exported=0)

        # 筛选目标日期（用会话创建时间；若缺则用更新时间）
        def _date_of(s: ChatSession) -> str:
            ts = s.create_time or s.update_time
            return get_date_from_ts(ts)

        target = [s for s in all_sessions if _date_of(s) == date_str]
        self.logger.info(f"筛选到 {len(target)} 条 {date_str} 的对话")
        if not target:
            self.logger.info(f"{date_str} 没有对话记录")
            generate_date_readme(date_folder, date_str, [], self.config.format, self.platform)
            return ExportResult(success=True, date=date_str, exported=0)

        exported_files = []
        for idx, session in enumerate(target, 1):
            self.logger.info(f"[{idx}/{len(target)}] 正在导出: {session.title}")
            safe_title = self._safe_filename(session.title)
            ext = self.config.format.value
            filename = f"{idx:02d}_{safe_title}.{ext}"
            filepath = date_folder / filename
            if self.export_session(session, filepath):
                exported_files.append({
                    "title": session.title,
                    "filename": filename,
                    "message_count": len(session.messages),
                })
                self.logger.info(f"  已保存: {filename} ({len(session.messages)} 条消息)")
            else:
                self.logger.error(f"  导出失败: {session.title}")
            time.sleep(self.config.request_delay)

        generate_date_readme(date_folder, date_str, exported_files, self.config.format, self.platform)
        return ExportResult(
            success=len(exported_files) > 0,
            date=date_str,
            exported=len(exported_files),
            files=exported_files,
            error=None if exported_files else "没有成功导出对话",
        )

    def export_all(self) -> List[ExportResult]:
        """导出全部对话（按日期分组），并生成总 README"""
        all_sessions = self.fetch_all_chats()
        if not all_sessions:
            self.logger.warning("没有获取到任何对话")
            return []

        date_groups: Dict[str, List[ChatSession]] = {}
        for s in all_sessions:
            ts = s.create_time or s.update_time
            date_str = get_date_from_ts(ts)
            date_groups.setdefault(date_str, []).append(s)

        results = []
        for date_str in sorted(date_groups.keys(), reverse=True):
            self.config.target_date = date_str
            results.append(self.export_by_date(date_str))
            time.sleep(1)

        generate_master_readme(self.output_dir, date_groups, self.config.format, self.platform)
        return results
