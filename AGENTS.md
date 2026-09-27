# AGENTS.md — CrayonTechCommunity 日报系统

> 本文件是所有 AI Agent 在此仓库中工作时的 **唯一权威上下文**。
> 修改代码前必须先读本文件；修改架构后必须同步更新本文件。

---

## 1. 项目概述

**CrayonTechCommunity** 是一个面向 QQ 技术社群的每日信息汇总系统。

核心目标：
- 自动采集多个 QQ 群的聊天记录
- 使用 LLM 生成每日日报（话题摘要、信息差、技术分享、活跃贡献者）
- 在群内推送精简版日报，同时提供 Web 端完整归档

用户画像：计算机领域博主运营的技术社群，多个 QQ 群，总计数千人。

---

## 2. 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                    QQ 群 × N                            │
│                       │                                 │
│              NapCat (NTQQ 协议端)                       │
│                       │ OneBot v11 协议                  │
│                       ▼                                 │
│              NoneBot2 (Bot 后端)                        │
│              src/bot/                                   │
│                       │                                 │
│         ┌─────────────┼─────────────┐                   │
│         ▼             ▼             ▼                   │
│   消息采集插件    日报生成插件    互动指令插件            │
│   (collector)    (digest)       (commands)              │
│         │             │                                 │
│         ▼             ▼                                 │
│      Storage 层 (SQLite/PostgreSQL)                     │
│      src/storage/                                       │
│         │                                               │
│         ▼                                               │
│      LLM 处理层 (摘要/分类/提取)                        │
│      src/llm/                                           │
│         │                                               │
│         ├──▶ 群内推送精简日报                            │
│         └──▶ Web API → 前端 Dashboard                   │
│              src/web/                                   │
└─────────────────────────────────────────────────────────┘
```

---

## 3. 技术栈

| 层级 | 技术选型 | 说明 |
|------|---------|------|
| QQ 协议端 | NapCat | 基于 NTQQ 客户端壳，相对稳定 |
| Bot 框架 | NoneBot2 + onebot v11 adapter | Python 生态，插件化架构 |
| 数据库 | SQLite（Phase 1）→ PostgreSQL（Phase 3） | 初期轻量，后期可迁移 |
| LLM | OpenAI API / 兼容接口（DeepSeek、Qwen 等） | 通过 config 切换 |
| Web 后端 | FastAPI | 与 NoneBot2 共享 Python 生态 |
| Web 前端 | Vue 3 + Vite | 轻量 SPA，展示日报和归档 |
| 部署 | Docker Compose | 一键部署所有服务 |

---

## 4. 目录结构

```
CrayonTechCommunity/
├── AGENTS.md                  # 本文件 — AI Agent 上下文
├── README.md                  # 项目介绍和使用说明
├── pyproject.toml             # Python 项目配置
├── docker-compose.yml         # 容器编排
├── config/
│   ├── .env.example           # 环境变量模板
│   ├── bot_config.yml         # NoneBot2 配置
│   └── llm_config.yml         # LLM 提供商配置
├── src/
│   ├── bot/                   # NoneBot2 Bot 层
│   │   ├── __init__.py
│   │   ├── bot.py             # Bot 入口
│   │   ├── plugins/           # NoneBot2 插件
│   │   │   ├── collector.py   # 消息采集：监听群消息，写入数据库
│   │   │   ├── digest.py      # 日报生成：定时触发 LLM 摘要，推送群内
│   │   │   └── commands.py    # 互动指令：@bot 查询、手动触发等
│   │   └── utils/             # Bot 层工具函数
│   │       ├── message_parser.py   # 消息解析（图片/链接/代码块提取）
│   │       └── group_manager.py    # 多群管理
│   ├── storage/               # 数据持久层
│   │   ├── __init__.py
│   │   ├── models.py          # ORM 模型（消息、日报、用户）
│   │   ├── database.py        # 数据库连接与初始化
│   │   └── queries.py         # 常用查询封装
│   ├── llm/                   # LLM 处理层
│   │   ├── __init__.py
│   │   ├── client.py          # LLM API 客户端（支持多 provider）
│   │   ├── prompts.py         # Prompt 模板管理
│   │   └── digest_generator.py # 日报生成逻辑
│   └── web/                   # Web 层
│       ├── api/               # FastAPI 后端
│       │   ├── __init__.py
│       │   ├── main.py        # FastAPI 入口
│       │   ├── routes/        # API 路由
│       │   └── deps.py        # 依赖注入
│       └── frontend/          # Vue 3 前端
│           ├── package.json
│           ├── src/
│           └── public/
├── scripts/                   # 运维脚本
│   ├── setup.sh               # 初始化脚本
│   └── export_import.sh       # QQ 聊天记录手动导入（降级方案）
├── docs/                      # 文档
│   ├── deployment.md          # 部署指南
│   └── api.md                 # API 文档
└── tests/                     # 测试
    ├── test_collector.py
    ├── test_digest.py
    └── test_llm.py
```

---

## 5. 核心模块职责

### 5.1 消息采集 (`src/bot/plugins/collector.py`)
- 监听所有已加入 QQ 群的消息事件
- 解析消息内容（纯文本、图片 OCR、链接预览、代码块）
- 写入 `messages` 表，字段包括：群号、发送者、时间、原始内容、解析后内容
- **不做任何过滤或判断**，全量存储，由下游 LLM 层决定什么值得摘要

### 5.2 日报生成 (`src/bot/plugins/digest.py` + `src/llm/digest_generator.py`)
- 每日定时触发（默认 22:00），也支持手动触发
- 从数据库拉取当日全部消息
- 调用 LLM 生成结构化日报：
  - **今日话题**：讨论了哪些技术话题，简要总结
  - **信息差 & 资源分享**：谁分享了什么链接/工具/文章
  - **技术亮点**：有深度的技术讨论摘要
  - **活跃贡献者**：当日高质量发言者
- 生成精简版（200-300 字）推送群内 + 完整版存入数据库供 Web 展示

### 5.3 互动指令 (`src/bot/plugins/commands.py`)
- `@bot 今日总结` — 手动触发当日日报
- `@bot 搜索 <关键词>` — 搜索历史消息
- `@bot 谁聊了 <话题>` — 查询特定话题的讨论者
- `@bot 本周热点` — 生成周报

### 5.4 Web 层 (`src/web/`)
- REST API 提供日报列表、详情、搜索接口
- 前端展示：日报时间线、全文搜索、贡献者排行、话题标签

---

## 6. 数据模型

```python
# src/storage/models.py

class Message:
    id: int                  # 主键
    group_id: str            # QQ 群号
    sender_id: str           # 发送者 QQ 号
    sender_name: str         # 发送者昵称
    content_raw: str         # 原始消息内容
    content_parsed: str      # 解析后的纯文本
    message_type: str        # text / image / link / code / file
    urls: list[str]          # 提取的 URL 列表
    created_at: datetime     # 消息发送时间
    collected_at: datetime   # 采集入库时间

class DailyDigest:
    id: int                  # 主键
    group_id: str            # 群号（"all" 表示跨群汇总）
    date: date               # 日报日期
    summary_short: str       # 精简版（推送到群）
    summary_full: str        # 完整版（Web 展示）
    topics: list[str]        # 话题标签
    contributors: list[dict] # 贡献者列表 [{id, name, highlight}]
    message_count: int       # 当日消息总数
    created_at: datetime     # 生成时间

class GroupInfo:
    group_id: str            # QQ 群号
    group_name: str          # 群名称
    is_active: bool          # 是否启用采集
    joined_at: datetime      # Bot 加入时间
```

---

## 7. 开发阶段

### Phase 1 — MVP（当前阶段）
- [x] 项目初始化、目录结构
- [ ] NoneBot2 + NapCat 对接
- [ ] 消息采集插件 + SQLite 存储
- [ ] LLM 日报生成（单群）
- [ ] 定时推送日报到群

### Phase 2 — Web 展示
- [ ] FastAPI 日报 API
- [ ] Vue 3 前端 Dashboard
- [ ] 日报归档和搜索

### Phase 3 — 增强功能
- [ ] 多群汇总日报
- [ ] 贡献者排行榜
- [ ] 话题自动分类和标签
- [ ] 周报/月报
- [ ] PostgreSQL 迁移

---

## 8. 编码规范

### Python
- Python >= 3.10，使用 type hints
- 格式化：Ruff（lint + format）
- 异步优先：NoneBot2 和 FastAPI 均基于 asyncio
- 数据库操作使用 SQLAlchemy 2.0 async
- 环境变量管理：pydantic-settings

### 前端
- Vue 3 Composition API + TypeScript
- 样式：Tailwind CSS
- 构建：Vite

### Git 规范
- 分支：`main` (稳定) / `dev` (开发) / `feat/*` (功能)
- Commit message：`feat:` / `fix:` / `docs:` / `chore:` 前缀
- PR 合并前需通过 lint 和测试

---

## 9. 环境变量

```env
# QQ Bot
NAPCAT_WS_URL=ws://localhost:3001          # NapCat WebSocket 地址
QQ_BOT_ACCOUNT=123456789                   # Bot QQ 号（小号）
TARGET_GROUPS=111111,222222,333333          # 监听的群号列表

# LLM
LLM_PROVIDER=openai                        # openai / deepseek / qwen
LLM_API_KEY=sk-xxx
LLM_MODEL=gpt-4o-mini                      # 日报生成用的模型
LLM_BASE_URL=https://api.openai.com/v1     # 兼容接口地址

# Database
DATABASE_URL=sqlite+aiosqlite:///./data/community.db

# Web
WEB_HOST=0.0.0.0
WEB_PORT=8080

# Schedule
DIGEST_CRON=0 22 * * *                     # 日报生成时间（每日 22:00）
```

---

## 10. 降级策略

当 NapCat 协议端不可用时（封号/协议失效）：

1. **手动导出模式**：管理员从 QQ 客户端导出聊天记录（TXT/HTML），通过 `scripts/export_import.sh` 导入数据库
2. **Web 端不受影响**：历史日报和搜索功能正常运行
3. **恢复后自动续接**：协议端恢复后，Bot 自动重新开始采集

---

## 11. 安全注意事项

- Bot QQ 号使用**小号**，不使用博主主号
- `.env` 文件**不得提交到 Git**，已在 `.gitignore` 中排除
- LLM API Key 通过环境变量注入，不硬编码
- Web 端如需公开访问，需加基础鉴权（Phase 2）
- QQ 号等用户隐私数据在 Web 展示时做脱敏处理

---

## 12. Agent 协作约定

- 修改任何模块的核心逻辑后，必须更新本文件对应章节
- 新增插件必须在「目录结构」和「核心模块职责」中登记
- 数据模型变更必须同步更新「数据模型」章节
- 环境变量新增必须同步更新「环境变量」章节和 `.env.example`
