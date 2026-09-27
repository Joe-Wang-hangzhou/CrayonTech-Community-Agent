# CrayonTechCommunity — QQ 群文本总结

本项目旨在为指定的 QQ 群提供自动化的文本消息采集与按日内容总结功能。当前为第一版 (V1.0)。

## 功能特性

1. **消息采集**：常驻运行的 NoneBot2 Bot，通过与 NapCat 的对接，采集配置中指定 QQ 群的纯文本消息，并安全写入 MySQL。
2. **按日总结**：提供独立的命令行工具 (CLI)，指定群号和日期后，从 MySQL 查询该群（以 `Asia/Shanghai` 时区处理）的当日消息，调用 OpenAI 兼容的 LLM 生成中文总结并输出到终端。

> **说明**：当前系统专注于纯文本内容提取，非文本消息（如图片、视频等）不解析。数据存储时使用 `(group_id, message_id)` 联合唯一约束以防止重复写入。

## 前提条件

- Python 3.10+
- 一台已运行的 MySQL 服务器，需预先创建数据库并分配具备建表与读写权限的账号（推荐字符集 `utf8mb4`）
- [NapCat](https://github.com/NapNeko/NapCatQQ) 客户端，已登录对应 QQ 账号并加入待采集的群组
- 可访问的 OpenAI 兼容 LLM 服务（需提供 API Key、模型名称和 Base URL）

## 快速开始

### 1. 准备 MySQL

```sql
CREATE DATABASE crayon_community CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'community'@'%' IDENTIFIED BY 'your-password';
GRANT ALL PRIVILEGES ON crayon_community.* TO 'community'@'%';
FLUSH PRIVILEGES;
```

### 2. 安装依赖

```bash
# 使用 uv（推荐）
uv sync

# 或使用 pip
pip install -e .
```

### 3. 配置环境变量

```bash
cp config/.env.example .env
# 编辑 .env，填入真实值
```

`.env` 文件已被 `.gitignore` 排除。需要填写的关键配置：

| 变量 | 说明 |
|------|------|
| `HOST` / `PORT` | NoneBot 监听地址与端口，NapCat 必须能网络访问此地址 |
| `ONEBOT_V11_ACCESS_TOKEN` | 安全鉴权 Token，需与 NapCat 侧配置保持一致 |
| `TARGET_GROUPS` | 逗号分隔的 QQ 群号 |
| `DATABASE_URL` | MySQL 连接串，格式：`mysql+asyncmy://用户名:密码@主机:端口/数据库名?charset=utf8mb4` |
| `LLM_API_KEY` | OpenAI 兼容服务的 API Key |
| `LLM_MODEL` | 使用的模型名（如 `gpt-4o-mini`） |
| `LLM_BASE_URL` | OpenAI 兼容 API Base URL |

### 4. 配置 NapCat

在 NapCat 网络配置中添加websocket客户端：

- **地址**：`ws://<NoneBot可达地址>:<PORT>/onebot/v11/ws`
  - 例如：`ws://127.0.0.1:16666/onebot/v11/ws`
- **Token**：填入你在 `.env` 中配置的 `ONEBOT_V11_ACCESS_TOKEN`

NapCat 作为 WebSocket 客户端将主动连接 NoneBot 的 WebSocket 服务端。若 NapCat 和 NoneBot 部署在不同机器，请确保 `.env` 中的 `HOST` 绑定了公网或内网可达的网卡地址（如 `0.0.0.0`）。

### 5. 启动 Bot

```bash
python -m src.bot.bot
```

Bot 启动时会自动检查并创建 MySQL 消息表（如果尚不存在）。启动成功后，Bot 将监听端口并等待 NapCat 连接。

### 6. 验证采集

在目标 QQ 群中发送一条纯文本消息，检查 Bot 控制台日志，若显示 `已存储消息` 的调试或信息日志，即说明数据链路打通。

### 7. 运行按日总结

在另一个终端窗口运行以下命令：

```bash
python -m src.summarize --group-id 123456789 --date 2025-09-27
```

- `--group-id`：待总结的 QQ 群号
- `--date`：YYYY-MM-DD 格式的自然日。系统按 `Asia/Shanghai` 时区查询当天的完整数据。

若当天该群没有采集到有效文本消息，程序会提示“该群当天没有已采集的文本消息”，不会消耗 LLM 的 Token。

## 连接架构

- NapCat 使用 OneBot v11 **反向 WebSocket 客户端**，主动连接到 NoneBot 监听的 `ws://<NoneBot可达地址>:<PORT>/onebot/v11/ws`。
- NoneBot 底层使用 FastAPI 驱动承载此 WebSocket 服务，当前架构下不提供额外的业务 Web API。
- 鉴权依赖于两端统一配置的 `ONEBOT_V11_ACCESS_TOKEN`。

## 项目结构

```
src/
├── __init__.py
├── bot/
│   ├── __init__.py
│   ├── bot.py              # NoneBot2 服务启动入口
│   ├── plugins/
│   │   ├── __init__.py
│   │   └── group_msg.py    # 群文本消息采集插件
│   └── utils/
│       └── __init__.py
├── storage/
│   ├── __init__.py
│   ├── database.py          # SQLAlchemy 异步引擎管理
│   └── models.py            # MySQL 消息表数据模型
├── summarize.py             # 按日总结 CLI 工具
├── llm/
│   └── __init__.py
└── web/                     # 预留目录
tests/
├── __init__.py
└── test_core.py              # V1.0 核心逻辑测试套件
config/
└── .env.example             # 环境变量配置模板
```

## 测试开发

```bash
# 安装包含开发工具的依赖包
uv sync --group dev

# 运行测试用例
uv run pytest tests/ -v
```

所有测试默认使用 SQLite 内存数据库运行，无需额外部署 MySQL 实例。

## 暂未支持的特性

以下功能在当前版本暂未实现，可能会在后续版本迭代：
Web 前端页面视图、业务 API 接口、Docker Compose 一键部署、定时任务生成日报、将总结自动推送至 QQ 群、Bot 群内互动指令、图片文字识别 (OCR)、跨群消息聚合总结、活跃度排行榜、周报或月报生成。
