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

# 3. 询问是否一并启动 NapCat QQ 客户端 Docker
read -p "🤔 是否需要通过 Docker 一并启动 NapCat (QQ 登录端)? (y/N): " start_docker
if [[ "$start_docker" =~ ^[Yy]$ ]]; then
    read -p "👉 请输入要登录的 QQ 号: " qq_account
    if [ -n "$qq_account" ]; then
        echo "🐳 正在启动 NapCat Docker..."
        # 停止并删除旧容器（如果存在）
        docker rm -f crayon-napcat &>/dev/null || true
        # 读取 .env 中的 HOST 和 PORT，若无则使用默认值
        NB_HOST=$(grep '^HOST=' .env | cut -d '=' -f2 || echo "127.0.0.1")
        NB_PORT=$(grep '^PORT=' .env | cut -d '=' -f2 || echo "8080")
        
        # 启动新的 NapCat 容器
        docker run -d \
            --name crayon-napcat \
            --network host \
            -v "$(pwd)/napcat_data:/app/napcat/config" \
            -e ACCOUNT="$qq_account" \
            -e WS_URL="ws://127.0.0.1:${NB_PORT}/onebot/v11/ws" \
            mlikiowa/napcat-docker:latest
        
        NAPCAT_DOCKER_STARTED=true
        echo "✅ NapCat Docker 已在后台启动 (容器名: crayon-napcat)"
        echo "⚠️ 请使用命令查看登录二维码: docker logs -f crayon-napcat"
    else
        echo "❌ 未输入 QQ 号，跳过 NapCat Docker 启动。"
    fi
fi

# 4. 同步依赖
echo "📦 正在检查并同步依赖包 (uv sync)..."
uv sync

echo "🟢 准备启动双进程服务..."

# 5. 启动 Bot 进程并放入后台
echo "--> 启动 NoneBot2 消息采集进程..."
uv run python -m src.bot.bot &
BOT_PID=$!

# 6. 启动 Web API 进程并放入后台
echo "--> 启动 FastAPI Web 接口与前端托管服务..."
uv run uvicorn src.web.api.main:app --host 127.0.0.1 --port 8000 &
WEB_PID=$!

# 7. 配置退出时的清理操作
cleanup() {
    echo ""
    echo "🛑 接收到退出信号，正在关闭服务..."
    kill $BOT_PID $WEB_PID 2>/dev/null
    wait $BOT_PID $WEB_PID 2>/dev/null
    
    if [ "$NAPCAT_DOCKER_STARTED" = true ]; then
        read -p "❓ 是否同时关闭并移除 NapCat Docker 容器 (crayon-napcat)? (y/N): " stop_docker
        if [[ "$stop_docker" =~ ^[Yy]$ ]]; then
            docker rm -f crayon-napcat
            echo "✅ NapCat 容器已关闭。"
        fi
    fi
    
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
