"""按日总结命令。

用法: python -m src.summarize --group-id <群号> --date YYYY-MM-DD
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from src.services.summary import (
    MAX_CHARS_PER_CHUNK,
    chunk_messages,
    fetch_messages,
    generate_and_save_summary,
    summarize_chunk,
)
from src.storage.database import close_engine, init_engine

__all__ = [
    "MAX_CHARS_PER_CHUNK",
    "chunk_messages",
    "fetch_messages",
    "generate_and_save_summary",
    "summarize_chunk",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按日群聊总结")
    parser.add_argument("--group-id", type=int, required=True, help="QQ 群号")
    parser.add_argument("--date", type=str, required=True, help="日期 YYYY-MM-DD")
    parser.add_argument("--force", action="store_true", help="强制重新生成总结并覆盖已有记录")
    return parser.parse_args()


async def run() -> None:
    args = parse_args()

    # 加载环境变量
    env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(env_path)

    # 解析日期
    try:
        day = date.fromisoformat(args.date)
    except ValueError:
        print(f"错误: 无效的日期格式 '{args.date}'，请使用 YYYY-MM-DD", file=sys.stderr)
        sys.exit(1)

    # 初始化数据库
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("错误: DATABASE_URL 环境变量未设置", file=sys.stderr)
        sys.exit(1)

    init_engine(database_url)

    try:
        try:
            summary = await generate_and_save_summary(
                group_id=args.group_id,
                date_obj=day,
                force_refresh=args.force,
            )
        except ValueError as e:
            print(f"错误: {e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            # 不输出 API Key
            api_key = os.getenv("LLM_API_KEY")
            error_msg = str(e)
            # 过滤可能泄漏的 key
            if api_key and api_key in error_msg:
                error_msg = error_msg.replace(api_key, "***")
            print(f"LLM 调用失败: {error_msg}", file=sys.stderr)
            sys.exit(1)

        if not summary:
            print(f"该群（{args.group_id}）在 {args.date} 当天没有已采集的文本消息")
            return

        # 输出总结
        print(f"\n===== 群 {args.group_id} 在 {args.date} 的聊天总结 =====")
        print(summary)
        print("===== 总结结束 =====")

    finally:
        await close_engine()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
