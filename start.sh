#!/usr/bin/env bash
set -e

echo "======================================"
echo "🚀 CrayonTechCommunity 一键启动脚本"
echo "======================================"

# 1. 检查环境变量配置
if [ ! -f .env ]; then
    echo "❌ 错误: 找不到 .env 文件！"
    echo "👉 请先执行 'cp config/.env.example .env' 并填入 MySQL 和 LLM 的真实信息。"
    exit 1
fi

# 2. 检查 uv 是否安装
if ! command -v uv &> /dev/null; then
    echo "❌ 错误: 未安装 uv。请先参考官方文档安装 uv，或使用 pip 替代运行。"
    exit 1
fi

# 3. 同步依赖
echo "📦 正在检查并同步依赖包 (uv sync)..."
uv sync

echo "🟢 准备启动双进程服务..."

# 4. 启动 Bot 进程并放入后台
echo "--> 启动 NoneBot2 消息采集进程..."
uv run python -m src.bot.bot &
BOT_PID=$!

# 5. 启动 Web API 进程并放入后台
echo "--> 启动 FastAPI Web 接口与前端托管服务..."
uv run uvicorn src.web.api.main:app --host 127.0.0.1 --port 8000 &
WEB_PID=$!

# 6. 配置退出时的清理操作
cleanup() {
    echo ""
    echo "🛑 接收到退出信号，正在关闭服务..."
    kill $BOT_PID $WEB_PID 2>/dev/null
    wait $BOT_PID $WEB_PID 2>/dev/null
    echo "✅ 服务已安全关闭。"
    exit 0
}

# 捕获 Ctrl+C (SIGINT) 和终止信号 (SIGTERM)
trap cleanup SIGINT SIGTERM

echo ""
echo "🎉 所有服务启动完毕！"
echo "🌐 前端访问地址: http://127.0.0.1:8000"
echo "💡 (若要在 QQ 端生效，请确保 NapCat 已连上 NoneBot)"
echo "📌 按 Ctrl+C 可同时关闭这两个服务。"
echo "======================================"
echo "实时日志输出中..."
echo ""

# 阻塞主脚本，等待子进程
wait $BOT_PID
wait $WEB_PID
