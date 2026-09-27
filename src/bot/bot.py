import os
from pathlib import Path

import nonebot
from dotenv import load_dotenv
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter


def main() -> None:
    # 1. 从项目根目录 .env 加载环境变量
    #    注意：NoneBot 的 dotenv 支持和 python-dotenv 是不同的机制
    #    我们用 python-dotenv 加载 .env 确保所有环境变量可用
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    load_dotenv(env_path)

    # 2. 初始化 NoneBot，使用 FastAPI 驱动
    nonebot.init(
        driver="~fastapi",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8080")),
        onebot_access_token=os.getenv("ONEBOT_V11_ACCESS_TOKEN", ""),
    )

    # 3. 注册 OneBot V11 适配器
    driver = nonebot.get_driver()
    driver.register_adapter(OneBotV11Adapter)

    # 4. 在 driver 启动时初始化数据库
    @driver.on_startup
    async def _init_db() -> None:
        from src.storage.database import create_tables, init_engine

        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL 环境变量未设置")
        init_engine(database_url)
        await create_tables()
        nonebot.logger.info("数据库连接成功，表已就绪")

    @driver.on_shutdown
    async def _close_db() -> None:
        from src.storage.database import close_engine

        await close_engine()
        nonebot.logger.info("数据库连接已关闭")

    # 5. 加载群消息插件
    nonebot.load_plugin("src.bot.plugins.group_msg")

    # 6. 运行 Bot
    nonebot.run()


if __name__ == "__main__":
    main()
