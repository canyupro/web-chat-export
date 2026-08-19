"""BrowserExporter：Playwright 浏览器收割引擎基类。

设计要点（实测教训沉淀）：
1. **持久化 profile**：launch_persistent_context + user_data_dir（按平台独立），
   登录一次写入磁盘，后续运行自动带登录态，不再重复登录。
2. **页面复用**：check_auth / fetch_all_chats 共用同一工作页面，
   登录后不关页，直到收割完成统一清理（避免登录态/缓存割裂）。
3. **API 响应监听收割**（_harvest_api_response）：页面自身带真实凭证发请求，
   直接收割 API 响应 JSON，绕开 HttpOnly Cookie / ut 令牌获取难题。
"""
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

from models import ExportConfig, ChatSession, ChatMessage
from exporters.base import BaseExporter


class BrowserError(Exception):
    """浏览器收割引擎错误"""
    pass


class BrowserExporter(BaseExporter):
    """基于 Playwright 的导出器基类"""

    platform = "browser"
    # 子类覆盖：登录后的主页 URL
    home_url: str = ""

    def __init__(self, config: ExportConfig):
        super().__init__(config)
        self._playwright = None
        self._context = None  # 持久化浏览器上下文
        self._work_page = None  # 复用的工作页面

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def _profile_dir(self) -> Path:
        """平台独立的持久化 profile 目录（登录一次永久保留）"""
        base = Path.home() / ".web_chat_export" / "profiles" / self.platform
        base.mkdir(parents=True, exist_ok=True)
        return base

    def _ensure_browser(self):
        """惰性启动持久化 Chromium 上下文（登录态落盘）。"""
        if self._context:
            return self._context
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise BrowserError(
                "需要 playwright：pip install playwright && playwright install chromium"
            )
        self._playwright = sync_playwright().start()
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self._profile_dir()),
            headless=self.config.headless,
        )
        return self._context

    def _get_work_page(self):
        """获取（或复用）工作页面：登录后保持，收割期间不关。"""
        ctx = self._ensure_browser()
        if self._work_page and not self._work_page.is_closed():
            return self._work_page
        # 复用上下文里已打开的页面（若有），否则新开
        pages = ctx.pages
        self._work_page = pages[0] if pages else ctx.new_page()
        return self._work_page

    def close(self) -> None:
        """统一清理：关工作页、关上下文（登录态已落盘，下次免登）。"""
        try:
            if self._work_page and not self._work_page.is_closed():
                self._work_page.close()
        except Exception:
            pass
        self._work_page = None
        if self._context:
            try:
                self._context.close()
            except Exception:
                pass
            self._context = None
        if self._playwright:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    # ------------------------------------------------------------------
    # 子类必须实现
    # ------------------------------------------------------------------
    def _login_and_prepare(self, page) -> None:
        """打开 home_url，等待登录态就绪（子类可等待某元素/全局变量出现）。"""
        raise NotImplementedError

    def get_session_ids(self, page) -> List[str]:
        """返回全部会话 ID 列表"""
        raise NotImplementedError

    def fetch_session_detail(self, page, conv_id: str) -> ChatSession:
        """根据会话 ID 获取 ChatSession（含 messages）"""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # 登录等待
    # ------------------------------------------------------------------
    def _wait_until_logged_in(self, page, timeout: float = 300.0) -> bool:
        """等待用户登录：headful 弹浏览器轮询登录态，不依赖 stdin。"""
        if self.config.headless:
            raise BrowserError("未登录且为无头模式，无法等待用户登录")
        self.logger.warning(
            f"请在打开的浏览器中登录（最多等 {int(timeout)} 秒，登录一次后写入本地 profile，下次免登）..."
        )
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(3)
            try:
                if self.is_logged_in(page):
                    self.logger.info("检测到已登录，继续...")
                    return True
            except Exception:
                pass
        raise BrowserError(f"等待登录超时（{int(timeout)} 秒）")

    def is_logged_in(self, page) -> bool:
        """子类覆盖：检测当前是否已登录（默认尝试取会话 ID）"""
        return len(self.get_session_ids(page)) > 0

    def _detect_logged_out(self, page) -> bool:
        """检测是否未登录。子类可覆盖（默认 True=认为需要登录）。"""
        return True

    # ------------------------------------------------------------------
    # API 响应监听收割（通用范式）
    # ------------------------------------------------------------------
    def _harvest_api_response(self, page, url_pattern: str, action,
                              timeout_ms: int = 15000) -> Optional[dict]:
        """导航/操作前挂网络监听，收割第一个匹配 url_pattern 的 API 响应 JSON。

        页面自身带真实凭证（ut/HttpOnly cookie）发请求，直接拿结构化响应，
        绕开一切凭证获取难题。action 是触发请求的回调（如 page.goto）。
        """
        captured = {}

        def on_response(response):
            try:
                if url_pattern in response.url and "json" in (response.headers.get("content-type") or ""):
                    captured["data"] = response.json()
            except Exception:
                pass

        page.on("response", on_response)
        try:
            action()
            elapsed = 0
            step = 500
            while elapsed < timeout_ms:
                if "data" in captured:
                    break
                page.wait_for_timeout(step)
                elapsed += step
            return captured.get("data")
        finally:
            try:
                page.remove_listener("response", on_response)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 收割管线（页面复用版）
    # ------------------------------------------------------------------
    def _prepare_and_get_ids(self, page) -> List[str]:
        """打开主页 -> （必要时）等登录 -> 拿会话 ID 列表。"""
        self._login_and_prepare(page)
        conv_ids = self.get_session_ids(page)
        if not conv_ids and self._detect_logged_out(page):
            self._wait_until_logged_in(page)
            # 登录后回主页重读
            page.goto(self.home_url)
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(2000)
            conv_ids = self.get_session_ids(page)
        return conv_ids

    def fetch_all_chats(self) -> List[ChatSession]:
        page = self._get_work_page()
        try:
            conv_ids = self._prepare_and_get_ids(page)
            self.logger.info(f"共发现 {len(conv_ids)} 个会话")
            sessions = []
            for i, conv_id in enumerate(conv_ids, 1):
                try:
                    session = self.fetch_session_detail(page, conv_id)
                    if session and session.messages:
                        sessions.append(session)
                        self.logger.info(f"  [{i}/{len(conv_ids)}] 已收割: {session.title} ({len(session.messages)} 条消息)")
                    else:
                        self.logger.warning(f"  [{i}/{len(conv_ids)}] 跳过（无消息）: {conv_id}")
                except Exception as e:
                    self.logger.warning(f"  [{i}/{len(conv_ids)}] 收割失败 {conv_id}: {e}")
                page.wait_for_timeout(300)
            return sessions
        finally:
            # 只关页面，不关上下文（登录态在持久化 profile，close 由外层统一调）
            pass

    # 浏览器引擎的认证检查：能打开主页且拿到会话即视为有效
    def check_auth(self) -> bool:
        try:
            page = self._get_work_page()
            conv_ids = self._prepare_and_get_ids(page)
            return len(conv_ids) > 0
        except Exception as e:
            self.logger.error(f"浏览器认证检查失败: {e}")
            return False
