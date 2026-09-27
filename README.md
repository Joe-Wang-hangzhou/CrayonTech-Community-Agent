# CrayonTechCommunity — QQ 群文本总结

本项目旨在为指定的 QQ 群提供自动化的文本消息采集与按日内容总结功能。当前为第一版 (V1.0)。

## 功能特性

1. **消息采集**：常驻运行的 NoneBot2 Bot，通过与 NapCat 的对接，采集配置中指定 QQ 群的纯文本消息，并安全写入 MySQL。
2. **按日总结 (Web & CLI)**：
   - 提供独立的 Web API 服务与前端可视化页面，支持在浏览器中一键生成和查看总结。
   - 大模型生成的总结结果会自动落库持久化，防止刷新页面重复消耗 Token。
   - 保留了原有的命令行工具 (CLI)，支持在终端触发和查看群消息总结。

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

在 NapCat 网络配置中添加 WebSocket 客户端：

- **地址**：`ws://<NoneBot可达地址>:<PORT>/onebot/v11/ws`
  - 例如：`ws://127.0.0.1:16666/onebot/v11/ws`
- **Token**：填入你在 `.env` 中配置的 `ONEBOT_V11_ACCESS_TOKEN`

NapCat 作为 WebSocket 客户端将主动连接 NoneBot 的 WebSocket 服务端。若 NapCat 和 NoneBot 部署在不同机器，请确保 `.env` 中的 `HOST` 绑定了公网或内网可达的网卡地址（如 `0.0.0.0`）。

### 5. 启动 Bot (数据采集进程)

```bash
uv run python -m src.bot.bot
```

Bot 启动时会自动检查并创建 MySQL 消息表（如果尚不存在）。启动成功后，Bot 将监听端口并等待 NapCat 连接。在目标 QQ 群中发送一条纯文本消息，检查 Bot 控制台日志，若显示 `已存储消息` 的调试或信息日志，即说明数据链路打通。

### 6. 启动 Web API 服务 (可视化前端)

在另一个终端窗口运行：

```bash
uv run uvicorn src.web.api.main:app --host 127.0.0.1 --port 8000
```
启动成功后，浏览器访问 `http://127.0.0.1:8000` 即可通过可视化界面生成和查看指定日期的总结。

*(如果你更喜欢命令行，依然可以使用 CLI：`uv run python -m src.summarize --group-id 123456789 --date 2025-09-27`)*

## 连接架构

采用 **前后端与采集服务相解耦** 的双进程架构：
1. **消息采集进程 (NoneBot2)**：承载 OneBot v11 反向 WebSocket 服务端，专职于高吞吐量的消息接收与 MySQL 落库。不提供业务 Web API，不受前端请求和长时间 LLM 调用的阻塞。
2. **Web API 进程 (FastAPI)**：通过 HTTP REST API 向前端提供数据，复用底层的 MySQL 存储层，完成查询与长耗时 LLM 总结。
3. **前端 (原生 Web)**：静态资源由 Web API 服务直接挂载提供，开箱即用。

## 项目结构

```
frontend/                    # 前端页面代码
src/
├── bot/                     # 消息采集进程逻辑
│   ├── bot.py               # NoneBot2 服务启动入口
│   └── plugins/
│       └── group_msg.py     # 群文本消息采集插件
├── services/                # 公共业务服务层
│   └── summary.py           # 群聊总结与大模型调用核心逻辑
├── storage/                 # 数据持久化层
│   ├── database.py          # SQLAlchemy 异步引擎管理
│   └── models.py            # MySQL 消息表与总结表模型
├── web/                     # 业务 Web API 进程
│   └── api/
│       └── main.py          # FastAPI 启动入口与路由
├── summarize.py             # 按日总结 CLI 工具
└── llm/
tests/                       # 测试套件 (SQLite 内存数据库)
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
Docker Compose 一键部署、定时任务生成日报、将总结自动推送至 QQ 群、Bot 群内互动指令、图片文字识别 (OCR)、跨群消息聚合总结、活跃度排行榜、周报或月报生成。
