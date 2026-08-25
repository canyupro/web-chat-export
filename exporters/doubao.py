"""豆包（Doubao）浏览器收割器。

基于实测（见项目记忆 doubao-web-api-findings）：
- 页面 SSR 直出：/chat/{conversationId} 内联 window._ROUTER_DATA，
  数据路径 loaderData['chat_layout']['chat_(id)/page']，
  messageList.message_list[]（正文在 content_block[].content.text_block.text，
  另有 tts_content / brief），conversationInfo（conversation_id/name/create_time）。
- 会话列表在 loaderData.chat_layout.trimmedChainRecentConvCells（20 条）+ 
  conversationListV2Snapshot；或从侧栏 /chat/{数字ID} 链接提取。
- IM 协议（POST /im/*）需要 HttpOnly cookie，浏览器收割完全绕开。

收割策略：逐会话导航 /chat/{id} -> 读 _ROUTER_DATA -> 解析。
"""
import json
from typing import List, Dict, Any, Optional

from models import ExportConfig, ChatSession, ChatMessage
from exporters.formatter import normalize_ts
from exporters.browser import BrowserExporter, BrowserError


class DoubaoBrowserExporter(BrowserExporter):
    """豆包网页端浏览器收割器"""

    platform = "doubao"
    home_url = "https://www.doubao.com/chat/"

    def _login_and_prepare(self, page) -> None:
        page.goto(self.home_url)
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(1500)
        try:
            login_btn = page.get_by_role("button", name="登录")
            if login_btn.count() > 0:
                self.logger.warning("豆包未登录，请在打开的浏览器中登录，然后按回车继续...")
                input("按回车继续...")
                page.wait_for_timeout(1000)
        except Exception:
            pass

    def get_session_ids(self, page) -> List[str]:
        # 从侧栏链接提取会话 ID：/chat/{数字ID}
        links = page.eval_on_selector_all(
            "a[href*='/chat/']",
            "els => els.map(e => (e.getAttribute('href')||'').match(/\\/chat\\/(\\d+)/)?.[1]).filter(Boolean)",
        )
        seen = []
        for sid in links:
            if sid and sid not in seen:
                seen.append(sid)
        self.logger.info(f"从侧栏提取 {len(seen)} 个会话 ID")
        return seen

    def iter_session_meta(self):
        """豆包侧栏拿不到会话时间戳，退化为 ID 判定（检测不到续聊更新）"""
        page = self._get_work_page()
        return [{"id": sid, "updated_ts": None} for sid in self.get_session_ids(page)]

    def fetch_one(self, session_id: str) -> ChatSession:
        """拉取单个会话（含消息），供增量更新使用"""
        page = self._get_work_page()
        return self.fetch_session_detail(page, session_id)

    def fetch_session_detail(self, page, conv_id: str) -> ChatSession:
        page.goto(f"https://www.doubao.com/chat/{conv_id}")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(1500)

        data = None
        for _ in range(10):
            try:
                data = page.evaluate("window._ROUTER_DATA")
                if data:
                    break
            except Exception:
                pass
            page.wait_for_timeout(500)
        if not data:
            raise BrowserError(f"会话 {conv_id} 未加载 _ROUTER_DATA")

        page_data = self._find_page_data(data)
        if not page_data:
            raise BrowserError(f"会话 {conv_id} 无 page 数据")

        conv_info = page_data.get("conversationInfo") or {}
        ml = page_data.get("messageList") or {}
        msg_list = ml.get("message_list") or []

        session = ChatSession(
            id=conv_info.get("conversation_id") or conv_id,
            title=conv_info.get("name") or "无标题对话",
            create_time=self._s_to_ms(conv_info.get("create_time")),
            update_time=self._s_to_ms(conv_info.get("update_time")),
        )
        session.messages = self._parse_messages(msg_list)
        return session

    @staticmethod
    def _find_page_data(data: Any) -> Optional[Dict[str, Any]]:
        try:
            ld = data["loaderData"]
        except Exception:
            return None
        # chat_layout 下挂 chat_(id)/page
        layout = (ld or {}).get("chat_layout") or {}
        if isinstance(layout, dict) and "chat_(id)/page" in layout:
            return layout["chat_(id)/page"]
        # 兜底遍历
        for val in (ld or {}).values():
            if isinstance(val, dict) and "chat_(id)/page" in val:
                return val["chat_(id)/page"]
            if isinstance(val, dict) and val.get("conversationInfo"):
                return val
        return None

    @staticmethod
    def _s_to_ms(ts) -> Optional[int]:
        """兼容别名（历史命名，实际归一为秒），公共实现见 exporters.formatter.normalize_ts"""
        return normalize_ts(ts)

    @staticmethod
    def _parse_messages(msg_list: List[Dict[str, Any]]) -> List[ChatMessage]:
        messages = []
        for m in msg_list:
            # 豆包 user_type: 1=用户侧, 2=助手侧（可能是数字或字符串）
            user_type = str(m.get("user_type") or "")
            role = "user" if user_type == "1" else "assistant"
            text = DoubaoBrowserExporter._extract_text(m)
            if not text:
                continue
            messages.append(ChatMessage(
                role=role,
                content=text,
                create_time=DoubaoBrowserExporter._s_to_ms(m.get("create_time")),
            ))
        return messages

    @staticmethod
    def _extract_text(m: Dict[str, Any]) -> str:
        blocks = m.get("content_block") or []
        parts = []
        for b in blocks:
            content = b.get("content") or {}
            tb = content.get("text_block") or {}
            if tb.get("text"):
                parts.append(tb["text"])
        if parts:
            return "\n".join(parts).strip()
        tts = m.get("tts_content")
        if tts:
            return str(tts).strip()
        brief = m.get("brief")
        if brief:
            return str(brief).strip()
        return ""
