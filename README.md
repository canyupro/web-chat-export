# Chat Export / 多平台对话导出工具

> 从网页端导出聊天会话数据（DeepSeek / ChatGPT / 千问 / 豆包 / Grok），按日期保存为 Markdown、JSON 或 HTML。
> 自动生成每日与总索引，方便归档浏览。

## 功能特性

- ✅ 支持 5 个平台：DeepSeek、ChatGPT、千问（原通义）、豆包、Grok
- ✅ 双引擎架构：
  - **HTTP 重放**：DeepSeek / ChatGPT（快，无浏览器依赖）
  - **浏览器收割**：千问 / 豆包 / Grok（Playwright 打开浏览器，登录后自动收割，绕开 HttpOnly Cookie 与动态签名）
- ✅ 按日期分组导出，自动生成每日 `README.md` 索引和总索引
- ✅ Markdown / JSON / HTML 三种格式
- ✅ 安全文件名处理、请求间隔防频率限制
- ✅ 平台无关的导出管线，新增平台只需实现「会话列表 + 消息解析」

## 安装

```bash
pip install -r requirements.txt
# 浏览器引擎需要（豆包/Grok/千问）：
playwright install chromium
cp .env.example .env
```

## 使用

```bash
# DeepSeek（默认，HTTP 重放）
python deepseek_export.py --all

# ChatGPT（HTTP 重放，需 socks 代理）
python deepseek_export.py --platform chatgpt --all --token "xxx" --socks-proxy "socks5://127.0.0.1:7890"

# 千问（浏览器引擎，自动收割）
python deepseek_export.py --platform qwen --engine browser --all

# 豆包（浏览器引擎）
python deepseek_export.py --platform doubao --engine browser --all

# Grok（浏览器引擎）
python deepseek_export.py --platform grok --engine browser --all

# 指定日期 / 格式
python deepseek_export.py --platform chatgpt --date 2026-08-18 --format json
```

## 各平台认证方式

| 平台 | 引擎 | 认证 | 凭证来源 |
|------|------|------|----------|
| DeepSeek | http | Cookie + Bearer Token | F12 拷请求头 |
| ChatGPT | http | Bearer Token（约 3 个月有效） | F12 找 `/api/auth/session` 的 accessToken；需 socks 代理穿透 Cloudflare |
| 千问 Qwen | browser | 登录态自动收割 | 无需手动凭证 |
| 豆包 Doubao | browser | HttpOnly Cookie | 无需手动凭证（纯 HTTP 拿不到） |
| Grok | browser | HttpOnly Cookie | 无需手动凭证（纯 HTTP 拿不到） |

> 千问也可用 HTTP 引擎（`--engine http --ut "..." --cookie "..."`），但 ut 是动态令牌易过期，推荐浏览器引擎。

## 命令行参数

| 参数 | 简写 | 说明 | 默认值 |
|------|------|------|--------|
| `--platform` | `-p` | `deepseek`/`chatgpt`/`qwen`/`doubao`/`grok` | `deepseek` |
| `--engine` | `-e` | `http`/`browser`（按平台自动选择） | 自动 |
| `--cookie` | `-c` | 登录 Cookie | 环境变量 / .env |
| `--token` | `-t` | Bearer Token | 环境变量 / .env |
| `--ut` | - | 千问 query 令牌 | 环境变量 / .env |
| `--socks-proxy` | - | socks5 代理（ChatGPT 需） | 环境变量 |
| `--date` | `-d` | 目标日期 `YYYY-MM-DD` | 今天 |
| `--all` | `-a` | 导出全部对话 | 仅当天 |
| `--output-dir` | `-o` | 输出目录 | `./{platform}_chats` |
| `--format` | `-f` | `md`/`json`/`html` | `md` |
| `--delay` | - | 请求间隔秒数 | `0.3` |
| `--headful` | - | 浏览器引擎有头模式 | 无头 |
| `--show-cookie-help` | - | 认证帮助 | - |

## 输出结构

```
chatgpt_chats/
├── README.md                    # 总索引
├── 2026-08-18/                  # 日期文件夹
│   ├── README.md                # 当日索引
│   ├── 01_对话标题1.md
│   └── 02_对话标题2.md
└── 2026-08-17/
    └── ...
```

## 架构

```
deepseek_export.py     # CLI 入口 + 向后兼容 DeepSeekChatExporter
models.py              # 跨平台数据类（ChatSession/ChatMessage/ExportConfig）
exporters/
  __init__.py          # 工厂 build_exporter(platform, engine)
  base.py              # 导出管线（按日期分组、README、渲染调度）
  formatter.py         # md/json/html 渲染、安全文件名
  http.py              # HTTP 重放引擎基类
  browser.py           # Playwright 浏览器收割引擎基类
  deepseek.py          # DeepSeek（HTTP）
  chatgpt.py           # ChatGPT（HTTP + socks 代理穿透）
  qwen.py / qwen_http.py  # 千问（browser / http）
  doubao.py            # 豆包（browser）
  grok.py              # Grok（browser）
```

**新增平台**：在 `exporters/` 加一个文件，实现 `check_auth()` + `fetch_all_chats()`（返回 `List[ChatSession]`），在工厂里注册即可，导出管线完全复用。

## 测试

```bash
# 全部单元测试（含原 DeepSeek 兼容测试）
python tests/test_export.py
python tests/test_exporters.py
```

## 注意事项

- 各平台 Cookie / Token 会过期，认证失败时重新获取。
- 工具使用非官方网页接口，请控制请求频率（`--delay` 可调）。
- ChatGPT 需本机 socks 代理才能穿透 Cloudflare（普通网络直连会被 403）。
- 浏览器引擎首次使用会弹出浏览器，登录后脚本自动收割。

## 许可证

MIT License。
