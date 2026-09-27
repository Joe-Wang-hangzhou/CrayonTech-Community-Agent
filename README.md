# 🖍️ CrayonTechCommunity — QQ 技术社群日报系统

> 自动采集 QQ 群聊天记录，使用 LLM 生成每日技术日报，群内推送 + Web 归档。

## ✨ 功能

- 📥 **消息采集** — 实时监听多个 QQ 群，全量存储聊天记录
- 📰 **每日日报** — LLM 自动生成话题摘要、信息差、技术亮点、活跃贡献者
- 🤖 **群内互动** — @bot 查询历史、搜索话题、手动触发日报
- 🌐 **Web Dashboard** — 日报归档、全文搜索、贡献者排行

## 🏗️ 技术栈

- **Bot 框架**：NoneBot2 + NapCat（QQ 协议端）
- **LLM**：OpenAI / DeepSeek / Qwen（可配置）
- **数据库**：SQLite（MVP）→ PostgreSQL
- **Web**：FastAPI + Vue 3
- **部署**：Docker Compose

## 🚀 快速开始

```bash
# 1. 克隆仓库
git clone https://github.com/your-username/CrayonTechCommunity.git
cd CrayonTechCommunity

# 2. 复制环境变量
cp config/.env.example config/.env
# 编辑 config/.env 填入你的配置

# 3. 安装依赖
pip install -e .

# 4. 启动 Bot
python -m src.bot.bot
```

详细部署指南见 [docs/deployment.md](docs/deployment.md)。

## 📖 文档

- [AGENTS.md](AGENTS.md) — 项目架构与 AI Agent 协作规范
- [docs/deployment.md](docs/deployment.md) — 部署指南
- [docs/api.md](docs/api.md) — API 文档

## 📋 开发计划

- [x] Phase 1 — 项目初始化
- [ ] Phase 1 — 消息采集 + 日报生成 MVP
- [ ] Phase 2 — Web Dashboard
- [ ] Phase 3 — 多群汇总、排行榜、周报月报

## 📄 License

MIT
