"""ChatProvider：数据源抽象契约。

数据源（平台 + 引擎）负责「取数」：认证检查 + 拉取全量会话（含消息）。
导出管线（ExportPipeline）只依赖这个契约，与具体平台/引擎无关。

- config: ExportConfig        导出配置（输出目录/格式/日期等）
- logger: logging.Logger      平台日志器
- check_auth() -> bool        认证是否有效
- fetch_all_chats() -> List[ChatSession]   全量会话（含消息）
- close()                     释放资源（浏览器上下文 / HTTP 会话）

新增平台 = 实现这个契约的数据源类 + 在工厂注册一行，导出能力完全复用。
"""
import logging
from typing import List

from models import ExportConfig, ChatSession


class ChatProvider:
    """数据源契约。子类实现 check_auth / fetch_all_chats 即可被管线使用。"""

    platform: str = "base"

    def __init__(self, config: ExportConfig):
        self.config = config
        self.logger = logging.getLogger(f"{self.platform.title()}Provider")

    # 子类必须实现
    def check_auth(self) -> bool:
        raise NotImplementedError

    def fetch_all_chats(self) -> List[ChatSession]:
        raise NotImplementedError

    def close(self) -> None:
        """释放资源（默认空实现；HTTP/浏览器引擎各自覆盖）。"""
        pass
