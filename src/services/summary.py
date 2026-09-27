"""群聊按日总结服务。

提供消息获取、按日切块、大模型调用及按日总结数据库落库（DailySummary）的核心业务逻辑。
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.storage.database import get_session
from src.storage.models import DailySummary, GroupMessage, SHANGHAI_TZ, get_shanghai_now

if TYPE_CHECKING:
    from collections.abc import Sequence

# 单次请求最大字符数（保守估计 ~4000 token ≈ 12000 中文字符）
MAX_CHARS_PER_CHUNK = 12000


async def fetch_messages(group_id: int, day: date) -> list[GroupMessage]:
    """查询指定群指定自然日（Asia/Shanghai）的所有消息，按发送时间排序。"""
    if isinstance(day, datetime):
        day = day.date()

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


def chunk_messages(
    messages: Sequence[GroupMessage],
    max_chars: int = MAX_CHARS_PER_CHUNK,
) -> list[str]:
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


async def generate_summary(
    messages: Sequence[GroupMessage],
    client: AsyncOpenAI,
    model: str,
) -> str:
    """分块调用 LLM 生成总结。"""
    chunks = chunk_messages(messages)
    if not chunks:
        return ""

    if len(chunks) == 1:
        return await summarize_chunk(client, model, chunks[0])

    print(f"消息量较大，分 {len(chunks)} 段处理...", file=sys.stderr)
    running_summary = ""
    for i, chunk in enumerate(chunks, 1):
        print(f"  正在处理第 {i}/{len(chunks)} 段...", file=sys.stderr)
        running_summary = await summarize_chunk(client, model, chunk, context=running_summary)
    return running_summary


async def get_daily_summary(group_id: int, date_obj: date) -> DailySummary | None:
    """查询指定群指定日期的已存总结。"""
    if isinstance(date_obj, datetime):
        date_obj = date_obj.date()

    async with get_session() as session:
        stmt = (
            select(DailySummary)
            .where(DailySummary.group_id == group_id)
            .where(DailySummary.summary_date == date_obj)
        )
        result = await session.execute(stmt)
        return result.scalars().first()


async def save_daily_summary(
    group_id: int,
    date_obj: date,
    content: str,
    message_count: int,
) -> DailySummary:
    """保存或更新群聊按日总结。"""
    if isinstance(date_obj, datetime):
        date_obj = date_obj.date()

    async with get_session() as session:
        stmt = (
            select(DailySummary)
            .where(DailySummary.group_id == group_id)
            .where(DailySummary.summary_date == date_obj)
        )
        result = await session.execute(stmt)
        record = result.scalars().first()

        if record is not None:
            record.summary_content = content
            record.message_count = message_count
            record.created_at = get_shanghai_now()
        else:
            record = DailySummary(
                group_id=group_id,
                summary_date=date_obj,
                summary_content=content,
                message_count=message_count,
                created_at=get_shanghai_now(),
            )
            session.add(record)

        try:
            await session.commit()
            return record
        except IntegrityError:
            await session.rollback()
            # 并发写入时处理竞争
            result = await session.execute(stmt)
            existing = result.scalars().first()
            if existing is not None:
                existing.summary_content = content
                existing.message_count = message_count
                existing.created_at = get_shanghai_now()
                await session.commit()
                return existing
            raise


async def generate_and_save_summary(
    group_id: int,
    date_obj: date,
    *,
    client: AsyncOpenAI | None = None,
    model: str | None = None,
    force_refresh: bool = False,
) -> str:
    """生成并保存指定群在指定日期的聊天总结。

    若当天已经生成过总结且未指定 force_refresh，直接返回已存的总结内容。
    若当日没有消息记录，返回空字符串。
    """
    if isinstance(date_obj, datetime):
        date_obj = date_obj.date()

    # 1. 检查是否已有缓存总结
    if not force_refresh:
        existing = await get_daily_summary(group_id, date_obj)
        if existing is not None:
            return existing.summary_content

    # 2. 查询当日消息
    messages = await fetch_messages(group_id, date_obj)
    if not messages:
        return ""

    print(f"查询到 {len(messages)} 条消息，正在生成总结...", file=sys.stderr)

    # 3. 准备 LLM 客户端与模型
    if client is None:
        api_key = os.getenv("LLM_API_KEY")
        base_url = os.getenv("LLM_BASE_URL")
        if not api_key:
            raise ValueError("LLM_API_KEY 环境变量未设置")
        client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    if model is None:
        model = os.getenv("LLM_MODEL")
        if not model:
            raise ValueError("LLM_MODEL 环境变量未设置")

    # 4. 调用 LLM 生成总结
    summary = await generate_summary(messages, client, model)

    # 5. 落库保存
    await save_daily_summary(
        group_id=group_id,
        date_obj=date_obj,
        content=summary,
        message_count=len(messages),
    )

    return summary
