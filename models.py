"""数据模型：跨平台统一的会话/消息/配置/结果结构。

这些数据类与平台无关，导出管线（md/json/html、按日期分组、README）只依赖它们。
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Optional, Any


class ExportFormat(Enum):
    """导出格式枚举"""
    MARKDOWN = "md"
    JSON = "json"
    HTML = "html"


@dataclass
class ChatMessage:
    """对话消息数据类"""
    role: str
    content: str
    create_time: Optional[int] = None


@dataclass
class ChatSession:
    """对话会话数据类"""
    id: str
    title: str
    create_time: Optional[int] = None
    update_time: Optional[int] = None
    messages: List[ChatMessage] = field(default_factory=list)


@dataclass
class ExportResult:
    """导出结果数据类"""
    success: bool
    date: str
    exported: int
    files: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class ExportConfig:
    """导出配置数据类

    注意：多平台认证字段使用通用名 cookie / bearer_token / ut，
    各平台适配器按自身需要取用，未用到的字段留空即可。
    """
    platform: str = "deepseek"
    engine: str = "http"  # http | browser
    cookie: str = ""
    bearer_token: str = ""
    ut: str = ""  # 千问的 query 令牌
    output_dir: str = "./chat_exports"
    target_date: Optional[str] = None
    export_all: bool = False
    format: ExportFormat = ExportFormat.MARKDOWN
    include_system_prompt: bool = False
    request_delay: float = 0.3
    timeout: int = 20
    headless: bool = True  # browser 引擎是否无头
    socks_proxy: str = ""  # chatgpt 穿透 Cloudflare 的 socks5 代理

    def __post_init__(self):
        # 兼容传字符串格式名（如 "md"）
        if isinstance(self.format, str):
            try:
                self.format = ExportFormat(self.format.lower())
            except ValueError:
                self.format = ExportFormat.MARKDOWN
