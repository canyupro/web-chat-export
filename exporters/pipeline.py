"""ExportPipeline：平台无关的导出管线。

消费任意 ChatProvider（鸭子类型：只需 config / logger / fetch_all_chats），
负责：按日期分组导出、md/json/html 渲染落盘、日期/总 README 生成。

- 单数据源：pipeline = ExportPipeline(provider); pipeline.export_by_date(...)
- 多数据源聚合：ExportPipeline.aggregate(providers, output_dir, fmt)
  把多个平台（如 deepseek + chatgpt）的会话按日期合并导出到一个归档目录。
"""
import csv
import logging
import re
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

# 全局索引文件名（位于输出目录根，跨批次按对话 ID upsert 合并）
INDEX_FILENAME = "index.csv"
INDEX_FIELDS = ["conversation_id", "platform", "title", "date", "file", "messages", "updated_at"]


class ExportPipeline:
    """导出管线：把「数据源产出的会话」落盘为按日期分组的文件与索引。"""

    def __init__(self, provider):
        self.provider = provider

    # ------------------------------------------------------------------
    # 内部便捷引用
    # ------------------------------------------------------------------
    @property
    def config(self) -> ExportConfig:
        return self.provider.config

    @property
    def logger(self) -> logging.Logger:
        return self.provider.logger

    @property
    def output_dir(self) -> Path:
        return Path(self.config.output_dir).resolve()

    def _safe_filename(self, name: str, max_length: int = 80) -> str:
        return safe_filename(name, max_length)

    # ------------------------------------------------------------------
    # 文件命名与全局索引
    # ------------------------------------------------------------------
    @staticmethod
    def session_filename(idx: int, session: ChatSession, ext: str) -> str:
        """会话文件名：{序号}_{标题}_{id前8位}.{ext}；无 id 时退回 {序号}_{标题}.{ext}。

        id 短码让同一对话跨批次导出的文件名稳定（序号/标题变化不影响追踪）。
        """
        safe_title = safe_filename(session.title)
        id8 = (session.id or "").strip()[:8]
        if id8 and all(c.isalnum() or c == "-" for c in id8):
            return f"{idx:02d}_{safe_title}_{id8}.{ext}"
        return f"{idx:02d}_{safe_title}.{ext}"

    def _upsert_index(self, rows: List[Dict[str, Any]]) -> None:
        """把本次导出条目按对话 ID 合并进全局索引 index.csv（保留其他日期/平台旧行）。"""
        index_path = self.output_dir / INDEX_FILENAME
        existing: Dict[str, Dict[str, str]] = {}
        if index_path.exists():
            try:
                with open(index_path, "r", encoding="utf-8-sig", newline="") as f:
                    for row in csv.DictReader(f):
                        cid = row.get("conversation_id")
                        if cid:
                            existing[cid] = row
            except Exception as e:
                self.logger.warning(f"读取已有 index.csv 失败（将重建）: {e}")
                existing = {}
        for row in rows:
            existing[row["conversation_id"]] = row
        merged = sorted(existing.values(),
                        key=lambda r: r.get("date") or "", reverse=True)
        with open(index_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=INDEX_FIELDS)
            writer.writeheader()
            writer.writerows(merged)

    # ------------------------------------------------------------------
    # 导出管线（与平台无关）
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
        """按日期导出全量会话中落在该日期的部分"""
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

        all_sessions = self.provider.fetch_all_chats()
        if not all_sessions:
            self.logger.warning("没有获取到任何对话")
            generate_date_readme(date_folder, date_str, [], self.config.format, self.provider.platform)
            return ExportResult(success=True, date=date_str, exported=0)

        # 筛选目标日期（用会话创建时间；若缺则用更新时间）
        def _date_of(s: ChatSession) -> str:
            ts = s.create_time or s.update_time
            return get_date_from_ts(ts)

        target = [s for s in all_sessions if _date_of(s) == date_str]
        self.logger.info(f"筛选到 {len(target)} 条 {date_str} 的对话")
        if not target:
            self.logger.info(f"{date_str} 没有对话记录")
            generate_date_readme(date_folder, date_str, [], self.config.format, self.provider.platform)
            return ExportResult(success=True, date=date_str, exported=0)

        exported_files = []
        index_rows = []
        for idx, session in enumerate(target, 1):
            self.logger.info(f"[{idx}/{len(target)}] 正在导出: {session.title}")
            ext = self.config.format.value
            filename = self.session_filename(idx, session, ext)
            filepath = date_folder / filename
            if self.export_session(session, filepath):
                exported_files.append({
                    "title": session.title,
                    "filename": filename,
                    "message_count": len(session.messages),
                })
                if session.id:
                    index_rows.append({
                        "conversation_id": session.id,
                        "platform": self.provider.platform,
                        "title": session.title,
                        "date": date_str,
                        "file": str(filepath.relative_to(self.output_dir)),
                        "messages": len(session.messages),
                        "updated_at": int(session.update_time) if session.update_time else "",
                    })
                self.logger.info(f"  已保存: {filename} ({len(session.messages)} 条消息)")
            else:
                self.logger.error(f"  导出失败: {session.title}")
            time.sleep(self.config.request_delay)

        generate_date_readme(date_folder, date_str, exported_files, self.config.format, self.provider.platform)
        if index_rows:
            try:
                self._upsert_index(index_rows)
            except Exception as e:
                self.logger.warning(f"更新 index.csv 失败: {e}")
        return ExportResult(
            success=len(exported_files) > 0,
            date=date_str,
            exported=len(exported_files),
            files=exported_files,
            error=None if exported_files else "没有成功导出对话",
        )

    def export_all(self) -> List[ExportResult]:
        """导出全部对话（按日期分组），并生成总 README"""
        all_sessions = self.provider.fetch_all_chats()
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
            results.append(self.export_by_date(date_str))
            time.sleep(1)

        generate_master_readme(self.output_dir, date_groups, self.config.format, self.provider.platform)
        return results

    # ------------------------------------------------------------------
    # 增量更新
    # ------------------------------------------------------------------
    def _read_known(self) -> Dict[str, Optional[int]]:
        """读 index.csv 为 {conversation_id: updated_at(int|None)}，供增量判定"""
        index_path = self.output_dir / INDEX_FILENAME
        known: Dict[str, Optional[int]] = {}
        if not index_path.exists():
            return known
        try:
            with open(index_path, "r", encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    cid = row.get("conversation_id")
                    if not cid:
                        continue
                    raw = str(row.get("updated_at") or "").strip()
                    known[cid] = int(float(raw)) if raw else None
        except Exception as e:
            self.logger.warning(f"读取 index.csv 失败（按空索引处理）: {e}")
        return known

    def _upsert_date_file(self, session: ChatSession) -> Optional[Dict[str, Any]]:
        """增量写入单个会话：同 ID 替换旧文件、序号接着当天已有文件递增，并更新索引。

        返回导出信息 dict；失败返回 None。
        """
        ts = session.create_time or session.update_time
        date_str = get_date_from_ts(ts)
        if date_str == "unknown":
            self.logger.warning(f"跳过（无时间戳）: {session.title}")
            return None
        date_folder = self.output_dir / date_str
        date_folder.mkdir(parents=True, exist_ok=True)
        id8 = (session.id or "").strip()[:8]

        # 同 ID 旧文件先删（会话续聊后重导，避免同内容双份）
        if id8:
            for old in date_folder.glob(f"*_{id8}.*"):
                if old.name != "README.md" and old.is_file():
                    old.unlink()
                    self.logger.info(f"  替换旧文件: {old.name}")

        # 序号接着该日期现有最大序号排，避免覆盖已有文件
        max_seq = 0
        for f in date_folder.glob("*.md"):
            m = re.match(r"^(\d+)_", f.name)
            if m and f.name != "README.md":
                max_seq = max(max_seq, int(m.group(1)))
        idx = max_seq + 1

        filename = self.session_filename(idx, session, self.config.format.value)
        filepath = date_folder / filename
        if not self.export_session(session, filepath):
            return None
        self.logger.info(f"  已保存: {date_str}/{filename} ({len(session.messages)} 条消息)")

        row = {
            "conversation_id": session.id,
            "platform": self.provider.platform,
            "title": session.title,
            "date": date_str,
            "file": str(filepath.relative_to(self.output_dir)),
            "messages": len(session.messages),
            "updated_at": int(session.update_time) if session.update_time else "",
        }
        try:
            self._upsert_index([row])
        except Exception as e:
            self.logger.warning(f"更新 index.csv 失败: {e}")
        return {"row": row, "filename": filename, "date_str": date_str}

    def _rebuild_date_readme(self, date_str: str) -> None:
        """增量写入后重建该日期的 README（扫目录文件 + index.csv 反查消息数）"""
        date_folder = self.output_dir / date_str
        files = sorted(
            f for f in date_folder.glob("*.md") if f.name != "README.md"
        )
        # 从索引反查标题/消息数（本次刚 upsert 的行一定在里面）
        meta_by_file: Dict[str, Dict[str, str]] = {}
        index_path = self.output_dir / INDEX_FILENAME
        if index_path.exists():
            try:
                with open(index_path, "r", encoding="utf-8-sig", newline="") as f:
                    for row in csv.DictReader(f):
                        meta_by_file[row.get("file") or ""] = row
            except Exception:
                pass
        entries = []
        for f in files:
            rel = f.relative_to(self.output_dir).as_posix()
            meta = meta_by_file.get(rel, {})
            title = meta.get("title") or re.sub(r"^\d+_", "", f.stem)
            try:
                count = int(meta.get("messages") or 0)
            except ValueError:
                count = 0
            entries.append({"title": title, "filename": f.name, "message_count": count})
        generate_date_readme(date_folder, date_str, entries,
                             self.config.format, self.provider.platform)

    def export_update(self) -> List[ExportResult]:
        """增量更新：从最新会话开始拉取，命中「已同步且未变化」的会话即停止。

        每个新/更新会话即时落盘（同 ID 替换、序号递增），index.csv 实时合并。
        返回按日期分组的 ExportResult 列表。
        """
        known = self._read_known()
        self.logger.info(f"增量更新: 索引中已有 {len(known)} 个会话")
        sessions = self.provider.fetch_updated_chats(known)
        self.logger.info(f"增量拉取到 {len(sessions)} 个新/更新会话")

        by_date: Dict[str, List[ChatSession]] = {}
        results: List[ExportResult] = []
        for s in sessions:
            info = self._upsert_date_file(s)
            if not info:
                continue
            self._rebuild_date_readme(info["date_str"])
            by_date.setdefault(info["date_str"], []).append(s)
        for date_str in sorted(by_date.keys(), reverse=True):
            group = by_date[date_str]
            results.append(ExportResult(
                success=True, date=date_str, exported=len(group),
                files=[{"title": s.title, "message_count": len(s.messages)} for s in group],
            ))
        return results

    # ------------------------------------------------------------------
    # 多数据源聚合导出
    # ------------------------------------------------------------------
    @classmethod
    def aggregate(cls, providers: List[Any], output_dir: str,
                  fmt: ExportFormat = ExportFormat.MARKDOWN) -> List[ExportResult]:
        """把多个数据源（不同平台）的会话按日期合并导出一个归档。

        流程：逐个 provider 拉取会话 → 合并 → 注入式 provider 复用 export_all
        落盘（按日期分组 + 总 README）→ 统一 close() 所有 provider。
        """
        if not providers:
            return []
        archive = Path(output_dir).resolve()
        archive.mkdir(parents=True, exist_ok=True)

        # 先收集所有平台的会话
        all_sessions: List[ChatSession] = []
        for p in providers:
            try:
                sessions = p.fetch_all_chats()
            except Exception as e:
                p.logger.error(f"聚合拉取失败（跳过）: {e}")
                sessions = []
            if not sessions:
                p.logger.warning("聚合拉取为空，跳过该平台")
            all_sessions.extend(sessions)
            p.logger.info(f"聚合: {p.platform} 贡献 {len(sessions)} 个会话")

        try:
            if not all_sessions:
                first = providers[0]
                first.logger.warning("所有平台均无会话，无内容可导出")
                return []

            # 注入式 provider：fetch_all_chats 返回已合并的会话
            from models import ExportConfig as _Config
            from exporters.provider import ChatProvider as _Provider

            class _AggregatedProvider(_Provider):
                platform = "all"

                def __init__(self, config, sessions):
                    super().__init__(config)
                    self._sessions = sessions

                def check_auth(self):
                    return True

                def fetch_all_chats(self):
                    return self._sessions

            agg_config = _Config(platform="all", engine="http", output_dir=str(archive), format=fmt)
            agg_provider = _AggregatedProvider(agg_config, all_sessions)
            return cls(agg_provider).export_all()
        finally:
            for p in providers:
                try:
                    p.close()
                except Exception:
                    pass
