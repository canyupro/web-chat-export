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

    # ------------------------------------------------------------------
    # 增量拉取钩子（子类按需实现，供 fetch_updated_chats 使用）
    # ------------------------------------------------------------------
    def iter_session_meta(self):
        """按新到旧返回会话元数据列表 [{id, updated_ts}]。

        updated_ts 为秒级 int；平台拿不到时间戳时置 None（退化为 ID 判定）。
        """
        raise NotImplementedError

    def fetch_one(self, session_id: str) -> ChatSession:
        """拉取单个会话（含消息）。"""
        raise NotImplementedError

    def fetch_updated_chats(self, known):
        """增量拉取：从最新会话开始，直到遇到「已知且未变化」的会话为止。

        known: {conversation_id: updated_ts(int|None)} 来自 index.csv。
        - ID 不在 known            -> 新会话，导出并继续
        - ID 在但 ts 变了/未知差异  -> 续聊更新，重导并继续
        - ID 在且 ts 一致          -> 后续全是旧数据，停止

        平台未实现 iter_session_meta 时回退全量拉取（由管线过滤）。
        """
        try:
            metas = self.iter_session_meta()
        except NotImplementedError:
            self.logger.info("平台不支持增量元数据，回退全量拉取")
            return [s for s in self.fetch_all_chats()
                    if s.id not in known or known.get(s.id) != s.update_time]
        sessions = []
        for meta in metas:
            sid = meta.get("id")
            if not sid:
                continue
            ts = meta.get("updated_ts")
            if sid in known:
                kts = known.get(sid)
                if ts is None or kts is None or kts == ts:
                    self.logger.info(f"增量: 命中已同步会话 {sid[:8]}，停止遍历")
                    break
                self.logger.info(f"增量: 会话 {sid[:8]} 有更新（{kts} -> {ts}），重新导出")
            try:
                s = self.fetch_one(sid)
            except Exception as e:
                self.logger.warning(f"增量: 拉取 {sid[:8]} 失败（跳过）: {e}")
                continue
            if s and s.messages:
                sessions.append(s)
            else:
                self.logger.info(f"增量: 会话 {sid[:8]} 无内容，跳过")
        return sessions
