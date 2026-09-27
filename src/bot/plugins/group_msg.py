import os
from datetime import datetime, timedelta, timezone

from nonebot import logger, on_message
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.rule import Rule
from sqlalchemy.exc import IntegrityError

from src.storage.database import get_session
from src.storage.models import GroupMessage

SHANGHAI_TZ = timezone(timedelta(hours=8))


def _get_target_groups() -> set[int]:
    """从环境变量解析目标群号。"""
    raw = os.getenv("TARGET_GROUPS", "")
    groups: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part:
            try:
                groups.add(int(part))
            except ValueError:
                logger.warning(f"TARGET_GROUPS 中无法解析的群号: {part}")
    return groups


def _is_target_group() -> Rule:
    """只处理来自目标群的消息。"""

    async def check(event: GroupMessageEvent) -> bool:
        target_groups = _get_target_groups()
        return event.group_id in target_groups

    return Rule(check)


# 注册消息匹配器
group_msg_handler = on_message(rule=_is_target_group(), priority=10, block=False)


@group_msg_handler.handle()
async def handle_group_message(event: GroupMessageEvent) -> None:
    # 提取纯文本
    text = event.get_plaintext().strip()
    if not text:
        return  # 没有有效文本，跳过

    # 将时间戳转换为 Asia/Shanghai 本地时间
    # event.time 是 Unix 时间戳（整数秒）
    utc_dt = datetime.fromtimestamp(event.time, tz=timezone.utc)
    shanghai_dt = utc_dt.astimezone(SHANGHAI_TZ)
    # 存入数据库时去掉时区信息，因为 MySQL DATETIME 不存时区
    naive_dt = shanghai_dt.replace(tzinfo=None)

    # 写入数据库
    async with get_session() as session:
        msg = GroupMessage(
            group_id=event.group_id,
            message_id=event.message_id,
            sent_at=naive_dt,
            content_text=text,
        )
        session.add(msg)
        try:
            await session.commit()
            logger.debug(f"已存储消息: group={event.group_id}, msg_id={event.message_id}")
        except IntegrityError:
            await session.rollback()
            logger.debug(f"重复消息已跳过: group={event.group_id}, msg_id={event.message_id}")
        except Exception as e:
            await session.rollback()
            logger.error(f"消息存储失败: {e}")
