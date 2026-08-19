"""
Chat 对话导出工具（多平台版）

从网页端获取聊天会话数据，按日期导出为 Markdown / JSON / HTML。

支持平台：
  - deepseek  chat.deepseek.com            （HTTP 重放）
  - chatgpt   chatgpt.com                  （HTTP 重放，需 socks 代理 + curl_cffi 可选）
  - qwen      www.qianwen.com              （browser 收割 / HTTP 重放需 ut）
  - doubao    www.doubao.com               （browser 收割）
  - grok      grok.com                     （browser 收割）

用法:
    python deepseek_export.py [--platform deepseek] [--engine http] [--date YYYY-MM-DD] [--all]

依赖:
    pip install -r requirements.txt
"""
import os
import sys
import json
import argparse
from dataclasses import asdict

# 向后兼容：数据类仍从 deepseek_export 顶层导出
from models import (
    ExportConfig,
    ExportFormat,
    ExportResult,
    ChatSession,
    ChatMessage,
)
from exporters import build_exporter, default_engine
from exporters.formatter import safe_filename as _safe_filename

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

try:
    import requests  # noqa: F401  （保持依赖显式）
except ImportError:
    print("[错误] 请先安装 requests: pip install requests")
    raise


# ============================================================
# 向后兼容：DeepSeekChatExporter 委托到新架构
# ============================================================
class DeepSeekChatExporter:
    """兼容层：旧类名委托到新的 DeepSeekHttpExporter。

    保留原 DeepSeek 行为（export_by_date / export_all / export_session /
    export_to_markdown / export_to_json / export_to_html / check_auth /
    get_chat_list / get_all_chats / get_chat_detail / parse_* / _format_timestamp /
    _get_date_from_chat / _safe_filename）。
    """

    def __init__(self, config):
        self._exporter = build_exporter(config)
        self.config = config
        self.logger = self._exporter.logger
        self.session = self._exporter.session
        self.cookie = config.cookie
        self.bearer_token = config.bearer_token

    # --- 认证 ---
    def check_auth(self) -> bool:
        return self._exporter.check_auth()

    # --- 平台数据获取（deepseek 专用） ---
    def get_chat_list(self, offset=0, limit=50, cursor=""):
        return self._exporter.get_chat_list(offset=offset, limit=limit, cursor=cursor)

    def get_all_chats(self):
        return self._exporter.get_all_raw_chats()

    def get_chat_detail(self, chat_id):
        return self._exporter.get_chat_detail(chat_id)

    def parse_chat_session(self, chat_info):
        return self._exporter.parse_chat_session(chat_info)

    def parse_messages(self, messages_data):
        return self._exporter.parse_messages(messages_data)

    # --- 导出 ---
    def export_to_markdown(self, session):
        from exporters.formatter import render_markdown
        return render_markdown(session)

    def export_to_json(self, session):
        from exporters.formatter import render_json
        return render_json(session)

    def export_to_html(self, session):
        from exporters.formatter import render_html
        return render_html(session)

    def export_session(self, session, output_path):
        return self._exporter.export_session(session, output_path)

    def export_by_date(self, target_date=None):
        return self._exporter.export_by_date(target_date)

    def export_all(self):
        return self._exporter.export_all()

    # --- 工具 ---
    def _safe_filename(self, name, max_length=80):
        from exporters.formatter import safe_filename
        return safe_filename(name, max_length)

    def _format_timestamp(self, ts):
        from exporters.formatter import format_timestamp
        return format_timestamp(ts)

    def _get_date_from_chat(self, chat_info):
        from exporters.formatter import get_date_from_ts
        update_time = chat_info.get("updated_at") or chat_info.get("create_time") or 0
        return get_date_from_ts(update_time)


def load_env_from_file():
    """从 .env 文件加载环境变量（支持 .env 和 .env.local）"""
    env_files = [".env.local", ".env"]
    loaded = False
    for env_file in env_files:
        if not os.path.exists(env_file):
            continue
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip()
                    if (value.startswith('"') and value.endswith('"')) or \
                       (value.startswith("'") and value.endswith("'")):
                        value = value[1:-1]
                    if key and key not in os.environ:
                        os.environ[key] = value
            loaded = True
            print(f"[INFO] 已加载环境变量: {env_file}")
        except Exception as e:
            print(f"[WARN] 加载 {env_file} 失败: {e}")
    return loaded


# 启动时自动加载 .env 文件
load_env_from_file()


def get_cookie_from_browser(platform: str = "deepseek"):
    """显示 Cookie 获取帮助"""
    help_texts = {
        "deepseek": """
╔══════════════════════════════════════════════════════════════╗
║               如何获取 DeepSeek Cookie/Token                  ║
╠══════════════════════════════════════════════════════════════╣
║  1. 打开浏览器，访问 https://chat.deepseek.com 并登录         ║
║  2. F12 → Network → 刷新 → 找发往 chat.deepseek.com 的请求    ║
║  3. 复制 Cookie 头 → DEEPSEEK_COOKIE                          ║
║  4. 复制 authorization 中 Bearer 后的值 → DEEPSEEK_BEARER_TOKEN║
╚══════════════════════════════════════════════════════════════╝
""",
        "chatgpt": """
╔══════════════════════════════════════════════════════════════╗
║              如何获取 ChatGPT Token                           ║
╠══════════════════════════════════════════════════════════════╣
║  1. 打开 chatgpt.com 登录                                      ║
║  2. F12 → Network → 找 /api/auth/session 请求                  ║
║  3. 复制响应 JSON 里的 accessToken → CHATGPT_BEARER_TOKEN      ║
║  4. 本机需 socks 代理（CHATGPT_SOCKS_PROXY）才能穿透 CF         ║
╚══════════════════════════════════════════════════════════════╝
""",
        "qwen": """
╔══════════════════════════════════════════════════════════════╗
║              如何获取千问 Cookie / ut                         ║
╠══════════════════════════════════════════════════════════════╣
║  推荐：--engine browser（浏览器收割，无需手动取凭证）           ║
║  HTTP 重放需：                                                 ║
║  1. 打开 www.qianwen.com 登录                                  ║
║  2. F12 → Network → 找 chat2-api.qianwen.com 请求              ║
║  3. 复制 URL 里的 ut 参数 → QWEN_UT                            ║
║  4. 复制 Cookie 头 → QWEN_COOKIE                               ║
╚══════════════════════════════════════════════════════════════╝
""",
        "doubao": """
╔══════════════════════════════════════════════════════════════╗
║            豆包：请使用浏览器引擎（--engine browser）          ║
╠══════════════════════════════════════════════════════════════╣
║  豆包认证依赖 HttpOnly Cookie，纯 HTTP 重放无法获取。           ║
║  使用浏览器引擎：脚本会打开浏览器，你登录后自动收割。           ║
╚══════════════════════════════════════════════════════════════╝
""",
        "grok": """
╔══════════════════════════════════════════════════════════════╗
║             Grok：请使用浏览器引擎（--engine browser）         ║
╠══════════════════════════════════════════════════════════════╣
║  Grok 认证依赖 HttpOnly Cookie，纯 HTTP 重放无法获取。          ║
║  使用浏览器引擎：脚本会打开浏览器，你登录后自动收割。           ║
╚══════════════════════════════════════════════════════════════╝
""",
    }
    print(help_texts.get(platform, help_texts["deepseek"]))


def create_parser() -> argparse.ArgumentParser:
    """创建命令行参数解析器"""
    parser = argparse.ArgumentParser(
        description="Chat 对话记录导出工具 v2.0.0（多平台）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 导出 DeepSeek 今天的对话（默认）
  python deepseek_export.py

  # 导出 ChatGPT 全部对话（需 socks 代理）
  python deepseek_export.py --platform chatgpt --all --token "xxx"

  # 用浏览器引擎导出千问（自动收割，推荐）
  python deepseek_export.py --platform qwen --engine browser --all

  # 导出 Grok
  python deepseek_export.py --platform grok --engine browser --all

  # 导出豆包
  python deepseek_export.py --platform doubao --engine browser --all

平台认证:
  deepseek: --cookie + --token
  chatgpt:  --token（CHATGPT_BEARER_TOKEN）
  qwen:     --engine browser 或 --cookie + --ut
  doubao:   --engine browser
  grok:     --engine browser

配置方式（优先级从高到低）:
  1. 命令行参数
  2. 环境变量（各平台前缀 *_COOKIE / *_TOKEN / *_UT）
  3. .env.local 文件
  4. .env 文件
""",
    )

    parser.add_argument("--platform", "-p", type=str, default="deepseek",
                        choices=["deepseek", "chatgpt", "qwen", "doubao", "grok"],
                        help="目标平台 (默认: deepseek)")
    parser.add_argument("--engine", "-e", type=str, default=None,
                        choices=["http", "browser"],
                        help="导出引擎: http=HTTP重放, browser=浏览器收割 (默认按平台自动)")
    parser.add_argument("--cookie", "-c", type=str, default=None,
                        help="登录 Cookie")
    parser.add_argument("--token", "-t", type=str, default=None,
                        help="Bearer Token（chatgpt/deepseek）")
    parser.add_argument("--ut", type=str, default=None,
                        help="千问 query 令牌（qwen HTTP 引擎）")
    parser.add_argument("--socks-proxy", type=str, default=None,
                        help="socks5 代理（chatgpt 需 CF 穿透，如 socks5://127.0.0.1:7890）")
    parser.add_argument("--date", "-d", type=str, default=None,
                        help="目标日期 (YYYY-MM-DD)，默认为今天")
    parser.add_argument("--all", "-a", action="store_true", default=False,
                        help="导出所有对话（按日期分组）")
    parser.add_argument("--output-dir", "-o", type=str, default=None,
                        help="输出目录 (默认: ./chat_exports 或平台目录)")
    parser.add_argument("--format", "-f", type=str,
                        choices=["md", "json", "html"], default="md",
                        help="导出格式: md=Markdown, json=JSON, html=HTML (默认: md)")
    parser.add_argument("--delay", type=float, default=0.3,
                        help="请求间隔秒数，避免频率限制 (默认: 0.3)")
    parser.add_argument("--headful", action="store_true", default=False,
                        help="浏览器引擎使用有头模式（便于登录）")
    parser.add_argument("--show-cookie-help", action="store_true", default=False,
                        help="显示如何获取认证信息的帮助")
    parser.add_argument("--version", "-v", action="version",
                        version="%(prog)s 2.0.0", help="显示版本信息")
    return parser


def _resolve_credentials(platform: str, args):
    """按平台从 命令行/环境变量 解析认证信息"""
    prefix = platform.upper()
    creds = {
        "cookie": args.cookie or os.environ.get(f"{prefix}_COOKIE", ""),
        "token": args.token or os.environ.get(f"{prefix}_BEARER_TOKEN", "") or os.environ.get(f"{prefix}_TOKEN", ""),
        "ut": args.ut or os.environ.get(f"{prefix}_UT", ""),
        "socks_proxy": args.socks_proxy or os.environ.get(f"{prefix}_SOCKS_PROXY", "")
                       or os.environ.get("SOCKS_PROXY", ""),
    }
    # deepseek 兼容旧变量名
    if platform == "deepseek":
        if not creds["cookie"]:
            creds["cookie"] = os.environ.get("DEEPSEEK_COOKIE", "")
        if not creds["token"]:
            creds["token"] = os.environ.get("DEEPSEEK_BEARER_TOKEN", "")
    if platform == "chatgpt" and not creds["token"]:
        creds["token"] = os.environ.get("CHATGPT_BEARER_TOKEN", "")
    return creds


def main():
    parser = create_parser()
    args = parser.parse_args()

    if args.show_cookie_help:
        get_cookie_from_browser(args.platform)
        return

    creds = _resolve_credentials(args.platform, args)
    engine = args.engine or default_engine(args.platform)

    # 校验认证（browser 引擎登录在运行时完成；http 引擎需凭证）
    if engine == "http" and args.platform in ("deepseek", "chatgpt"):
        if not creds["token"]:
            print(f"错误: {args.platform} 需要 Bearer Token。")
            print(f"  命令行 --token，或环境变量 {args.platform.upper()}_BEARER_TOKEN")
            print(f"\n运行 --show-cookie-help 查看获取方法。")
            sys.exit(1)
    if engine == "http" and args.platform == "deepseek" and not creds["cookie"]:
        print("错误: deepseek 需要 Cookie。请通过 --cookie 或 DEEPSEEK_COOKIE 提供。")
        sys.exit(1)

    output_dir = args.output_dir or os.environ.get("OUTPUT_DIR") or f"./{args.platform}_chats"

    config = ExportConfig(
        platform=args.platform,
        engine=engine,
        cookie=creds["cookie"],
        bearer_token=creds["token"],
        ut=creds["ut"],
        socks_proxy=creds.get("socks_proxy", ""),
        output_dir=output_dir,
        target_date=args.date,
        export_all=args.all,
        format=ExportFormat(args.format),
        request_delay=args.delay,
        headless=not args.headful,
    )

    # 构建导出器
    exporter = build_exporter(config)

    print("=" * 60)
    print(f"{args.platform.upper()} 对话记录导出工具 v2.0.0")
    print(f"引擎: {engine}")
    print("=" * 60)

    # 认证检查（browser 引擎会弹出浏览器等待登录）
    if not exporter.check_auth():
        print("\n认证失败或未登录，请检查凭证后重试。")
        print("运行 --show-cookie-help 查看获取方法。")
        sys.exit(1)

    # 执行导出
    try:
        if args.all:
            print("\n开始导出所有对话...\n")
            results = exporter.export_all()
            total_exported = sum(r.exported for r in results)
            result_data = {
                "success": True,
                "total_exported": total_exported,
                "dates": {r.date: r.exported for r in results},
            }
        else:
            print("\n开始导出对话...\n")
            result = exporter.export_by_date(target_date=args.date)
            result_data = asdict(result)

        print("\n" + "=" * 60)
        print("导出完成!")
        print("=" * 60)
        print(json.dumps(result_data, ensure_ascii=False, indent=2))
        sys.exit(0 if result_data.get("success") else 1)

    except KeyboardInterrupt:
        print("\n\n操作已取消")
        sys.exit(130)
    except Exception as e:
        print(f"\n导出过程中发生错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
