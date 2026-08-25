"""导出排版层：与平台无关。

包含：安全文件名、md/json/html 三种格式渲染、按日期分组、日期/总 README 生成。
这些逻辑从原 deepseek_export.py 抽出，行为保持一致。
"""
import re
import json
import html as html_mod
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from models import ChatSession, ChatMessage, ExportFormat

# 文件名安全字符替换映射
UNSAFE_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_filename(name: str, max_length: int = 80) -> str:
    """将标题转换为安全的文件名"""
    safe = UNSAFE_FILENAME_CHARS.sub("_", name.strip())
    safe = safe.strip(". ")
    if len(safe) > max_length:
        safe = safe[:max_length].rstrip(". ")
    return safe or "untitled"


def format_timestamp(ts: Optional[int]) -> str:
    """格式化时间戳（兼容秒/毫秒/None）"""
    if not ts:
        return "未知"
    try:
        if isinstance(ts, (int, float)):
            if ts > 1e12:
                ts = ts / 1000
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        return str(ts)
    except (ValueError, OSError):
        return str(ts)


def normalize_ts(value) -> Optional[int]:
    """秒/毫秒时间戳归一为秒级 int（>1e12 视为毫秒）；无法解析返回 None"""
    if value is None:
        return None
    try:
        v = int(value)
        return v if v < 1e12 else int(v / 1000)
    except (ValueError, TypeError):
        return None


def iso_to_ts(value) -> Optional[int]:
    """ISO 时间字符串转秒级时间戳（如 2026-08-17T05:55:44.370119Z）；无法解析返回 None"""
    if not value:
        return None
    try:
        v = str(value).replace("Z", "+00:00")
        return int(datetime.fromisoformat(v).timestamp())
    except (ValueError, TypeError):
        return None


def _format_message_to_markdown(message: ChatMessage) -> str:
    """将单条消息转换为 Markdown 格式"""
    role_icons = {
        "user": "👤",
        "assistant": "🤖",
        "system": "⚙️",
    }
    icon = role_icons.get(message.role, "❓")
    return f"## {icon} {message.role.capitalize()}\n\n{message.content}\n"


def render_markdown(session: ChatSession) -> str:
    """将对话导出为 Markdown 格式"""
    lines = [
        f"# {session.title}",
        "",
        f"> **对话ID**: `{session.id}`",
        f"> **创建时间**: {format_timestamp(session.create_time)}",
        f"> **更新时间**: {format_timestamp(session.update_time)}",
        "",
        "---",
        "",
    ]
    for msg in session.messages:
        lines.append(_format_message_to_markdown(msg))
        lines.append("")
    return "\n".join(lines)


def render_json(session: ChatSession) -> str:
    """将对话导出为 JSON 格式"""
    data = {
        "id": session.id,
        "title": session.title,
        "create_time": session.create_time,
        "update_time": session.update_time,
        "messages": [
            {
                "role": msg.role,
                "content": msg.content,
                "create_time": msg.create_time,
            }
            for msg in session.messages
        ],
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


def render_html(session: ChatSession) -> str:
    """将对话导出为 HTML 格式"""
    html_parts = [
        "<!DOCTYPE html>",
        "<html>",
        "<head>",
        f"<title>{html_mod.escape(session.title)}</title>",
        "<meta charset=\"UTF-8\">",
        "<style>",
        "body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; line-height: 1.6; }",
        ".header { background: #f5f5f5; padding: 15px; border-radius: 8px; margin-bottom: 20px; }",
        ".message { margin: 20px 0; padding: 15px; border-radius: 8px; }",
        ".user { background: #e3f2fd; }",
        ".assistant { background: #f3e5f5; }",
        ".role { font-weight: bold; margin-bottom: 10px; }",
        ".content { white-space: pre-wrap; }",
        "</style>",
        "</head>",
        "<body>",
        f"<h1>{html_mod.escape(session.title)}</h1>",
        "<div class=\"header\">",
        f"<p><strong>对话ID:</strong> {html_mod.escape(session.id)}</p>",
        f"<p><strong>创建时间:</strong> {format_timestamp(session.create_time)}</p>",
        f"<p><strong>更新时间:</strong> {format_timestamp(session.update_time)}</p>",
        "</div>",
    ]

    for msg in session.messages:
        role_class = "user" if msg.role == "user" else "assistant" if msg.role == "assistant" else "system"
        html_parts.append(f'<div class="message {role_class}">')
        html_parts.append(f'<div class="role">{html_mod.escape(msg.role.capitalize())}</div>')
        html_parts.append(f'<div class="content">{html_mod.escape(msg.content)}</div>')
        html_parts.append('</div>')

    html_parts.extend(["</body>", "</html>"])
    return "\n".join(html_parts)


def render_session(session: ChatSession, fmt: ExportFormat) -> str:
    """按格式渲染会话内容"""
    if fmt == ExportFormat.JSON:
        return render_json(session)
    if fmt == ExportFormat.HTML:
        return render_html(session)
    return render_markdown(session)


def get_date_from_ts(ts: Optional[int]) -> str:
    """从时间戳提取日期字符串（YYYY-MM-DD）"""
    if not ts:
        return "unknown"
    try:
        if isinstance(ts, (int, float)):
            if ts > 1e12:
                ts = ts / 1000
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        return "unknown"
    except (ValueError, OSError):
        return "unknown"


def generate_date_readme(folder: Path, date_str: str,
                         exported_files: List[Dict[str, Any]], fmt: ExportFormat,
                         platform: str = "") -> None:
    """生成日期文件夹的 README"""
    platform_label = f"{platform} " if platform else ""
    lines = [
        f"# {platform_label}对话记录 - {date_str}",
        "",
        f"导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"对话数量: {len(exported_files)}",
        f"导出格式: {fmt.value.upper()}",
        "",
    ]
    if exported_files:
        lines.append("## 对话列表")
        lines.append("")
        lines.append("| 序号 | 标题 | 消息数 | 文件 |")
        lines.append("|------|------|--------|------|")
        for idx, f in enumerate(exported_files, 1):
            lines.append(f"| {idx} | {f['title']} | {f['message_count']} | [{f['filename']}]({f['filename']}) |")
        lines.append("")
    (folder / "README.md").write_text("\n".join(lines), encoding="utf-8")


def generate_master_readme(output_dir: Path, date_groups: Dict[str, List],
                           fmt: ExportFormat, platform: str = "") -> None:
    """生成总 README"""
    total_chats = sum(len(v) for v in date_groups.values())
    platform_label = f"{platform} " if platform else ""
    lines = [
        f"# {platform_label}对话记录汇总",
        "",
        f"导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"覆盖日期数: {len(date_groups)}",
        f"总对话数: {total_chats}",
        f"导出格式: {fmt.value.upper()}",
        "",
        "## 按日期浏览",
        "",
        "| 日期 | 对话数 | 链接 |",
        "|------|--------|------|",
    ]
    for date_str in sorted(date_groups.keys(), reverse=True):
        count = len(date_groups[date_str])
        lines.append(f"| {date_str} | {count} | [{date_str}/]({date_str}/README.md) |")
    lines.extend([
        "",
        "---",
        "",
        f"*由 {platform or 'chat'}_export 自动生成*",
    ])
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")
