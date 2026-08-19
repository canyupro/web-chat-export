---
name: "web-chat-export"
description: "Export web conversations from DeepSeek / ChatGPT / Qwen / Doubao / Grok as Markdown/JSON/HTML by date. 从多个 AI 平台网页端自动导出每日对话记录并按日期存储。支持 HTTP 重放与浏览器收割双引擎，多平台聚合导出。"
version: "2.1.0"
author: "SOLO"
tags: ["chat", "export", "backup", "multi-platform", "automation"]
---

# 多平台对话记录自动导出

## 概述

从 DeepSeek / ChatGPT / 千问 / 豆包 / Grok 网页端获取对话记录，按日期分组存储为独立文件。支持 Markdown / JSON / HTML 三种格式，自动生成每日与总索引。

## 核心脚本

- **主脚本**: `deepseek_export.py` — CLI 入口（多平台）
- **架构**: `models.py` + `exporters/`（provider/pipeline/base/http/browser + 各平台适配器）
- **测试**: `tests/test_export.py`（兼容）+ `tests/test_exporters.py`（多平台）+ `tests/test_pipeline.py`（管线）

## 平台与引擎

| 平台 | 引擎 | 说明 |
|------|------|------|
| DeepSeek | http（默认） | Cookie + Bearer Token |
| ChatGPT | http（默认） | Bearer Token + socks 代理 |
| 千问 Qwen | browser（默认） | 浏览器收割，绕开 ut 签名 |
| 豆包 Doubao | browser（必须） | HttpOnly Cookie |
| Grok | browser（必须） | HttpOnly Cookie |

## 快速开始

### 安装

```bash
pip install -r requirements.txt
playwright install chromium   # 浏览器引擎需要
cp .env.example .env
```

### 运行

```bash
# DeepSeek（默认）
python deepseek_export.py --all

# ChatGPT（需 socks 代理 + token）
python deepseek_export.py --platform chatgpt --all --token "xxx" --socks-proxy "socks5://127.0.0.1:7890"

# 千问 / 豆包 / Grok（浏览器引擎，自动收割）
python deepseek_export.py --platform qwen --engine browser --all
python deepseek_export.py --platform doubao --engine browser --all
python deepseek_export.py --platform grok --engine browser --all

# 指定日期或格式
python deepseek_export.py --platform chatgpt --date 2026-08-18 --format json
```

### 浏览器引擎说明

千问 / 豆包 / Grok 用 `--engine browser` 时：
1. 脚本启动 Chromium（默认无头，`--headful` 可见）
2. 若未登录会提示你在浏览器里登录
3. 登录后脚本自动收割会话列表 + 消息，无需手动复制任何 Cookie

> 浏览器引擎需要 `playwright install chromium`（首次约 100MB+）。

## 命令行参数

| 参数 | 简写 | 说明 |
|------|------|------|
| `--platform` | `-p` | deepseek/chatgpt/qwen/doubao/grok |
| `--engine` | `-e` | http/browser |
| `--cookie` | `-c` | Cookie |
| `--token` | `-t` | Bearer Token |
| `--ut` | - | 千问 ut 令牌 |
| `--socks-proxy` | - | socks5 代理（ChatGPT） |
| `--date` | `-d` | 目标日期 YYYY-MM-DD |
| `--all` | `-a` | 全部对话 |
| `--output-dir` | `-o` | 输出目录 |
| `--format` | `-f` | md/json/html |
| `--headful` | - | 浏览器可见模式 |

## 测试

```bash
python tests/test_export.py       # 原 DeepSeek 兼容测试（12 项）
python tests/test_exporters.py    # 多平台导出器测试（9 项）
python tests/test_pipeline.py     # 导出管线测试（4 项）
```

## 更新日志

### v2.1.0
- 数据源（ChatProvider）与导出管线（ExportPipeline）解耦：`exporters/provider.py` + `exporters/pipeline.py`
- 新增 `--all-platforms` 多平台聚合导出（已登录平台按日期归档到 `./chats_archive/`）
- 修复 Skill 安装脚本未打包 `models.py` / `exporters/` 的 bug
- `build_exporter` 改为 `build_provider` 的兼容别名（对象类型不变）

### v2.0.0
- 重构为「平台适配器 + 双引擎（HTTP 重放 / 浏览器收割）」架构
- 新增 ChatGPT / 千问 / 豆包 / Grok 支持
- 新增 `--platform` / `--engine` 命令行选项
- 新增 `tests/test_exporters.py` 多平台测试

### v1.0.0
- 初始版本，仅 DeepSeek

## 许可证

MIT License
