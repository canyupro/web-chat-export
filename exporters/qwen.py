"""千问（Qwen）浏览器收割器 -- API 响应监听范式。

核心思路（实测验证的通用收割范式）：
  页面自身持有真实凭证（ut / Cookie），自己会调用 chat2-api 接口。
  收割器只需「导航到会话页 + 监听网络响应」，直接收割 msg/list 的 JSON，
  拿到结构化消息（含角色字段），完全绕开 ut 获取难题与 DOM 解析。

- 会话列表：localStorage['qw_cache_sidebar:{uid}:first-page-sessions']（免认证）
- 消息：导航 /chat/{sessionId} 时收割 chat2-api.qianwen.com 的 msg/list 响应
- 登录：headful 模式等用户登录（千问不拦 Playwright，实测放行）
"""
import json
from typing import List, Dict, Any, Optional

from models import ExportConfig, ChatSession, ChatMessage
from exporters.browser import BrowserExporter, BrowserError

GATEWAY = "chat2-api.qianwen.com"


class QwenBrowserExporter(BrowserExporter):
    """千问网页端浏览器收割器（API 响应监听）"""

    platform = "qwen"
    home_url = "https://www.qianwen.com/"

    def __init__(self, config: ExportConfig):
        super().__init__(config)
        # 会话 ID -> 侧栏缓存元数据（fetch_all_chats 时填充）
        self._meta_by_id: Dict[str, Dict[str, Any]] = {}

    def _login_and_prepare(self, page) -> None:
        page.goto(self.home_url)
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(1500)

    def is_logged_in(self, page) -> bool:
        """登录判定：侧栏缓存存在且有会话（登录后才有）"""
        cache = self._read_sidebar_cache(page)
        return bool(cache and cache.get("items"))

    def _read_sidebar_cache(self, page) -> Optional[Dict[str, Any]]:
        """从 localStorage 读会话列表缓存（含元数据）"""
        try:
            keys = page.evaluate("Object.keys(localStorage)")
        except Exception:
            return None
        key = next((k for k in keys
                    if "qw_cache_sidebar:" in k and k.endswith(":first-page-sessions")), None)
        if not key:
            return None
        try:
            raw = page.evaluate(f"localStorage['{key}']")
            if not raw:
                return None
            d = json.loads(raw)
            value = json.loads(d["value"]) if isinstance(d.get("value"), str) else d.get("value", {})
            return value
        except Exception:
            return None

    def get_session_ids(self, page) -> List[str]:
        cache = self._read_sidebar_cache(page)
        if cache and cache.get("items"):
            ids = [it.get("sessionId") for it in cache["items"] if it.get("sessionId")]
            if ids:
                self.logger.info(f"从侧栏缓存读取 {len(ids)} 个会话")
                return ids
        # 缓存缺失则退回侧栏链接
        self.logger.info("侧栏缓存缺失，从页面链接提取会话")
        links = page.eval_on_selector_all(
            "a[href*='/chat/']",
            "els => els.map(e => (e.getAttribute('href')||'').match(/\\/chat\\/([0-9a-f]{32})/)?.[1]).filter(Boolean)",
        )
        seen = []
        for sid in links:
            if sid and sid not in seen:
                seen.append(sid)
        return seen

    def fetch_session_detail(self, page, conv_id: str) -> ChatSession:
        """导航会话页并收割 msg/list API 响应（页面自带真实 ut）"""
        url = f"https://www.qianwen.com/chat/{conv_id}"

        data = self._harvest_api_response(
            page,
            url_pattern="/api/v1/session/msg/list",
            action=lambda: page.goto(url, wait_until="domcontentloaded"),
            timeout_ms=15000,
        )
        if not data:
            raise BrowserError(f"会话 {conv_id} 未捕获到 msg/list 响应")

        # 响应结构（实测）：{code:0, data:{list:[...]}} 或顶层 list
        payload = data.get("data") or {}
        msg_items = payload.get("list") or data.get("list") or []
        if not msg_items:
            raise BrowserError(f"会话 {conv_id} msg/list 响应无消息")

        # 会话元数据从侧栏缓存补（标题/时间）
        meta = self._meta_by_id.get(conv_id, {})
        session = ChatSession(
            id=conv_id,
            title=meta.get("summary") or f"会话 {conv_id[:8]}",
            create_time=self._ts(meta.get("createTime")),
            update_time=self._ts(meta.get("modifiedTime")),
        )
        session.messages = self._parse_api_messages(msg_items)
        return session

    def iter_session_meta(self):
        """按新到旧返回会话元数据（供增量更新）；顺带填充 _meta_by_id 供 fetch_one 用"""
        page = self._get_work_page()
        self._login_and_prepare(page)
        cache = None
        for _ in range(10):
            cache = self._read_sidebar_cache(page)
            if cache and cache.get("items"):
                break
            page.wait_for_timeout(1500)
        items = (cache or {}).get("items") or []
        self._meta_by_id = {
            it.get("sessionId"): it for it in items if it.get("sessionId")
        }
        return [{
            "id": it.get("sessionId"),
            "updated_ts": self._ts(it.get("modifiedTime")),
        } for it in items]

    def fetch_one(self, session_id: str) -> ChatSession:
        """拉取单个会话（含消息），供增量更新使用"""
        page = self._get_work_page()
        return self.fetch_session_detail(page, session_id)

    def fetch_all_chats(self) -> List[ChatSession]:
        """先在工作页面读缓存建立 ID->元数据映射，再走基类收割循环。"""
        page = self._get_work_page()
        self._login_and_prepare(page)
        # 等侧栏缓存就绪（登录后首页加载写入）
        cache = None
        for _ in range(10):
            cache = self._read_sidebar_cache(page)
            if cache and cache.get("items"):
                break
            page.wait_for_timeout(1500)
        self._meta_by_id = {
            it.get("sessionId"): it for it in ((cache or {}).get("items") or [])
            if it.get("sessionId")
        }
        # 复用基类循环（同一工作页面收割）
        return super().fetch_all_chats()

    @staticmethod
    def _ts(value) -> Optional[int]:
        if value is None:
            return None
        try:
            v = int(value)
            return v if v < 1e12 else int(v / 1000)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _parse_api_messages(msg_items: List[Dict[str, Any]]) -> List[ChatMessage]:
        """解析 msg/list 响应。真实结构（实测 dump）：每条 = 一轮对话，
        request_messages[] = 用户消息，response_messages[] = 助手消息。
        """
        messages = []

        def _visible_text(msgs) -> str:
            """收集一轮里可见的文本消息（跳过 hidden/系统类）"""
            parts = []
            for mm in msgs or []:
                mt = mm.get("mime_type") or ""
                if "hidden" in mt:
                    continue
                c = mm.get("content")
                if isinstance(c, str) and c.strip():
                    parts.append(c.strip())
            return "\n".join(p for p in parts if p)

        for turn in msg_items:
            # 用户侧
            user_text = _visible_text(turn.get("request_messages"))
            if user_text:
                messages.append(ChatMessage(
                    role="user",
                    content=user_text,
                    create_time=QwenBrowserExporter._ts(turn.get("request_timestamp") or turn.get("create_time")),
                ))
            # 助手侧
            asst_text = _visible_text(turn.get("response_messages"))
            if asst_text:
                messages.append(ChatMessage(
                    role="assistant",
                    content=asst_text,
                    create_time=QwenBrowserExporter._ts(turn.get("response_timestamp") or turn.get("update_time")),
                ))
        return messages
