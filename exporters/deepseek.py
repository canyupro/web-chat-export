"""DeepSeek 网页端 HTTP 导出器。

移植自原 deepseek_export.py 的 DeepSeekChatExporter，行为保持一致，
但接入统一 BaseExporter 管线（fetch_all_chats 产出 ChatSession 列表）。
"""
import logging
import time
from typing import List, Dict, Any, Optional

from models import ExportConfig, ChatSession, ChatMessage
from exporters.http import HttpExporter, AuthenticationError, RateLimitError, HttpError

BASE_URL = "https://chat.deepseek.com"
API_BASE = f"{BASE_URL}/api/v0"

# 请求头模板（基于实际抓包数据）
HEADERS_TEMPLATE = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36 Edg/139.0.0.0",
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Content-Type": "application/json",
    "Origin": BASE_URL,
    "Referer": f"{BASE_URL}/",
    "x-app-version": "2.0.0",
    "x-client-locale": "zh_CN",
    "x-client-platform": "web",
    "x-client-timezone-offset": "28800",
    "x-client-version": "2.0.0",
}


class DeepSeekHttpExporter(HttpExporter):
    """DeepSeek 网页端对话导出器"""

    platform = "deepseek"
    api_base = API_BASE
    headers_template = HEADERS_TEMPLATE

    def _apply_auth(self, config: ExportConfig) -> None:
        self.cookie = config.cookie.strip()
        self.bearer_token = config.bearer_token.strip()
        self.session.headers["Cookie"] = self.cookie
        if self.bearer_token:
            self.session.headers["Authorization"] = f"Bearer {self.bearer_token}"

    def check_auth(self) -> bool:
        if self._auth_checked:
            return True
        try:
            self._make_request("GET", "/client/settings?scope=model")
            self.logger.info("认证成功")
            self._auth_checked = True
            return True
        except AuthenticationError as e:
            self.logger.error(f"认证失败: {e}")
            return False
        except HttpError as e:
            self.logger.error(f"认证检查失败: {e}")
            return False

    def get_chat_list(self, offset: int = 0, limit: int = 50, cursor: str = "") -> tuple:
        """获取对话列表（兼容旧接口签名）"""
        query_string = f"lte_cursor={cursor}" if cursor else "lte_cursor.pinned=false"
        data = self._make_request("GET", f"/chat_session/fetch_page?{query_string}")
        biz_data = data.get("data", {}).get("biz_data", {})
        chats = biz_data.get("chat_sessions", [])
        has_more = biz_data.get("has_more", False)
        self.logger.info(f"获取到 {len(chats)} 条对话 (has_more={has_more})")
        return chats, has_more

    def get_all_raw_chats(self) -> List[Dict[str, Any]]:
        """获取所有原始对话记录（自动分页，带去重）"""
        all_chats = []
        seen_ids = set()
        cursor = ""
        page_num = 0
        max_pages = 5000
        same_count = 0
        last_count = -1

        while page_num < max_pages:
            page_num += 1
            try:
                chats, has_more = self.get_chat_list(cursor=cursor)
                if not chats:
                    break
                new_count = 0
                for chat in chats:
                    chat_id = chat.get("id", "")
                    if chat_id and chat_id not in seen_ids:
                        seen_ids.add(chat_id)
                        all_chats.append(chat)
                        new_count += 1
                if new_count == 0:
                    same_count += 1
                    if same_count >= 3:
                        self.logger.info(f"连续 {same_count} 页无新数据，停止获取")
                        break
                else:
                    same_count = 0
                if not has_more:
                    break
                last_chat = chats[-1]
                last_time = last_chat.get("updated_at", 0)
                if last_time:
                    cursor = str(last_time)
                else:
                    break
                if page_num % 50 == 0:
                    self.logger.info(f"第 {page_num} 页完成，共 {len(all_chats)} 条唯一对话，继续获取下一页...")
                time.sleep(self.config.request_delay)
            except RateLimitError:
                self.logger.warning("触发频率限制，等待 5 秒后重试...")
                time.sleep(5)
                continue

        self.logger.info(f"共获取到 {len(all_chats)} 条唯一对话（{page_num} 页）")
        return all_chats

    def get_chat_detail(self, chat_id: str) -> Optional[Dict[str, Any]]:
        """获取单个对话的详细内容"""
        try:
            data = self._make_request("GET", f"/chat/history_messages?chat_session_id={chat_id}")
            return data.get("data", {})
        except HttpError as e:
            self.logger.warning(f"获取对话 {chat_id} 详情失败: {e}")
            return None

    def parse_chat_session(self, chat_info: Dict[str, Any]) -> ChatSession:
        """解析对话信息为 ChatSession"""
        return ChatSession(
            id=chat_info.get("id", ""),
            title=chat_info.get("title", "无标题对话"),
            create_time=chat_info.get("created_at"),
            update_time=chat_info.get("updated_at"),
        )

    def parse_messages(self, messages_data: List[Dict[str, Any]]) -> List[ChatMessage]:
        """解析消息列表（适配 DeepSeek v0 API 的 fragments 结构）"""
        messages = []
        for msg_data in messages_data:
            role = msg_data.get("role", "unknown").lower()
            inserted_at = msg_data.get("inserted_at")
            fragments = msg_data.get("fragments", [])
            content_parts = []
            for frag in fragments:
                frag_type = frag.get("type", "")
                frag_content = frag.get("content", "")
                if frag_type == "REQUEST" and role == "user":
                    content_parts.append(frag_content)
                elif frag_type == "RESPONSE" and role == "assistant":
                    content_parts.append(frag_content)
                elif frag_type in ("THINK", "TOOL_SEARCH"):
                    pass  # 跳过思考过程与工具调用
            content = "\n".join(content_parts).strip()
            if content:
                messages.append(ChatMessage(role=role, content=content, create_time=inserted_at))
        return messages

    def fetch_all_chats(self) -> List[ChatSession]:
        """拉取全量会话（含消息），供统一导出管线使用"""
        all_sessions = []
        for chat_info in self.get_all_raw_chats():
            session = self.parse_chat_session(chat_info)
            detail = self.get_chat_detail(session.id)
            if not detail:
                self.logger.warning(f"  跳过（无法获取详情）: {session.title}")
                continue
            biz_data = detail.get("biz_data", {})
            messages_data = biz_data.get("chat_messages", [])
            if not messages_data:
                self.logger.warning(f"  跳过（无消息内容）: {session.title}")
                continue
            session.messages = self.parse_messages(messages_data)
            all_sessions.append(session)
            time.sleep(self.config.request_delay)
        return all_sessions
