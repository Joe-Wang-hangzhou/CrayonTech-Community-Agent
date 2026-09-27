"""按日总结命令。

用法: python -m src.summarize --group-id <群号> --date YYYY-MM-DD
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI
from sqlalchemy import select

from src.storage.database import close_engine, get_session, init_engine
from src.storage.models import GroupMessage

SHANGHAI_TZ = timezone(timedelta(hours=8))

# 单次请求最大字符数（保守估计 ~4000 token ≈ 12000 中文字符）
MAX_CHARS_PER_CHUNK = 12000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按日群聊总结")
    parser.add_argument("--group-id", type=int, required=True, help="QQ 群号")
    parser.add_argument("--date", type=str, required=True, help="日期 YYYY-MM-DD")
    return parser.parse_args()


async def fetch_messages(group_id: int, day: date) -> list[GroupMessage]:
    """查询指定群指定自然日（Asia/Shanghai）的所有消息，按发送时间排序。"""
    start = datetime(day.year, day.month, day.day, 0, 0, 0)
    end = start + timedelta(days=1)

    async with get_session() as session:
        stmt = (
            select(GroupMessage)
            .where(GroupMessage.group_id == group_id)
            .where(GroupMessage.sent_at >= start)
            .where(GroupMessage.sent_at < end)
            .order_by(GroupMessage.sent_at)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


def chunk_messages(messages: list[GroupMessage], max_chars: int = MAX_CHARS_PER_CHUNK) -> list[str]:
    """将消息列表按字符数切分为多个块。每块是格式化后的文本。"""
    chunks: list[str] = []
    current_lines: list[str] = []
    current_len = 0

    for msg in messages:
        line = f"[{msg.sent_at.strftime('%H:%M:%S')}] {msg.content_text}"
        line_len = len(line)

        if current_len + line_len > max_chars and current_lines:
            chunks.append("\n".join(current_lines))
            current_lines = []
            current_len = 0

        current_lines.append(line)
        current_len += line_len + 1  # +1 for newline

    if current_lines:
        chunks.append("\n".join(current_lines))

    return chunks


async def summarize_chunk(client: AsyncOpenAI, model: str, text: str, context: str = "") -> str:
    """对单个文本块调用 LLM 生成总结。"""
    system_prompt = (
        "你是一个群聊记录总结助手。请根据以下聊天记录，生成一份简洁的中文总结。"
        "只总结有记录支撑的内容，不要编造发言、人物或链接。"
        "总结应该包含主要讨论话题、关键观点和结论。"
    )

    user_content = ""
    if context:
        user_content += f"前文总结：\n{context}\n\n---\n\n"
    user_content += f"聊天记录：\n{text}"

    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=0.3,
    )

    return response.choices[0].message.content or ""


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
        # 查询消息
        messages = await fetch_messages(args.group_id, day)

        if not messages:
            print(f"该群（{args.group_id}）在 {args.date} 当天没有已采集的文本消息")
            return

        print(f"查询到 {len(messages)} 条消息，正在生成总结...", file=sys.stderr)

        # 检查 LLM 配置
        api_key = os.getenv("LLM_API_KEY")
        model = os.getenv("LLM_MODEL")
        base_url = os.getenv("LLM_BASE_URL")

        if not api_key:
            print("错误: LLM_API_KEY 环境变量未设置", file=sys.stderr)
            sys.exit(1)
        if not model:
            print("错误: LLM_MODEL 环境变量未设置", file=sys.stderr)
            sys.exit(1)

        # 创建 OpenAI 客户端
        client = AsyncOpenAI(api_key=api_key, base_url=base_url)

        # 分块总结
        chunks = chunk_messages(messages)

        try:
            if len(chunks) == 1:
                summary = await summarize_chunk(client, model, chunks[0])
            else:
                # 逐段总结，将前段总结作为上下文传给下一段
                print(f"消息量较大，分 {len(chunks)} 段处理...", file=sys.stderr)
                running_summary = ""
                for i, chunk in enumerate(chunks, 1):
                    print(f"  正在处理第 {i}/{len(chunks)} 段...", file=sys.stderr)
                    running_summary = await summarize_chunk(
                        client, model, chunk, context=running_summary
                    )
                summary = running_summary
        except Exception as e:
            # 不输出 API Key
            error_msg = str(e)
            # 过滤可能泄漏的 key
            if api_key and api_key in error_msg:
                error_msg = error_msg.replace(api_key, "***")
            print(f"LLM 调用失败: {error_msg}", file=sys.stderr)
            sys.exit(1)

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
