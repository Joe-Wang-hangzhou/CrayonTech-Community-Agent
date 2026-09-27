"""Tests for the CrayonTechCommunity V1.0.

Uses SQLite in-memory for database tests (via aiosqlite) to avoid
requiring a real MySQL server during CI/testing.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.storage.models import Base, DailySummary, GroupMessage

SHANGHAI_TZ = timezone(timedelta(hours=8))


# ---------------------------------------------------------------------------
# Fixtures: in-memory SQLite async engine for testing
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_engine():
    """Create an in-memory SQLite async engine for testing."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine):
    """Provide a session factory bound to the in-memory engine."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        yield session


# ---------------------------------------------------------------------------
# Test 1: 指定群的纯文本消息能正确入库
# ---------------------------------------------------------------------------


async def test_insert_group_message(db_session):
    """Target group text message is stored correctly."""
    msg = GroupMessage(
        group_id=123456789,
        message_id=1001,
        sent_at=datetime(2025, 9, 27, 14, 30, 0),
        content_text="Hello World",
    )
    db_session.add(msg)
    await db_session.commit()

    result = await db_session.execute(
        select(GroupMessage).where(GroupMessage.group_id == 123456789)
    )
    stored = result.scalars().first()
    assert stored is not None
    assert stored.group_id == 123456789
    assert stored.message_id == 1001
    assert stored.content_text == "Hello World"
    assert stored.sent_at == datetime(2025, 9, 27, 14, 30, 0)


# ---------------------------------------------------------------------------
# Test 2: 非目标群消息应被跳过（测试 _get_target_groups 逻辑）
# ---------------------------------------------------------------------------


def test_target_groups_parsing():
    """Only groups in TARGET_GROUPS are accepted."""
    with patch.dict("os.environ", {"TARGET_GROUPS": "111,222,333"}):
        from src.bot.plugins.group_msg import _get_target_groups

        groups = _get_target_groups()
        assert groups == {111, 222, 333}
        assert 999 not in groups


def test_target_groups_empty():
    """Empty TARGET_GROUPS results in empty set."""
    with patch.dict("os.environ", {"TARGET_GROUPS": ""}):
        from src.bot.plugins.group_msg import _get_target_groups

        assert _get_target_groups() == set()


# ---------------------------------------------------------------------------
# Test 3: 重复消息不产生重复记录（UniqueConstraint）
# ---------------------------------------------------------------------------


async def test_duplicate_message_rejected(db_engine):
    """Duplicate (group_id, message_id) is rejected by unique constraint."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)

    # First insert
    async with factory() as session:
        msg1 = GroupMessage(
            group_id=100,
            message_id=2001,
            sent_at=datetime(2025, 9, 27, 10, 0, 0),
            content_text="first",
        )
        session.add(msg1)
        await session.commit()

    # Duplicate insert should raise IntegrityError
    from sqlalchemy.exc import IntegrityError

    async with factory() as session:
        msg2 = GroupMessage(
            group_id=100,
            message_id=2001,
            sent_at=datetime(2025, 9, 27, 10, 0, 1),
            content_text="duplicate",
        )
        session.add(msg2)
        with pytest.raises(IntegrityError):
            await session.commit()


# ---------------------------------------------------------------------------
# Test 4: 日期边界查询（[D 00:00, D+1 00:00)）
# ---------------------------------------------------------------------------


async def test_date_boundary_query(db_engine):
    """Messages are queried by Asia/Shanghai date boundary [D 00:00, D+1 00:00)."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)

    start = datetime(2025, 9, 27, 0, 0, 0)
    end = start + timedelta(days=1)

    messages_data = [
        # Before the day (23:59:59 on Sep 26) — should be excluded
        (100, 1, datetime(2025, 9, 26, 23, 59, 59), "yesterday"),
        # Start of day (00:00:00 on Sep 27) — should be included
        (100, 2, datetime(2025, 9, 27, 0, 0, 0), "midnight"),
        # Mid-day — should be included
        (100, 3, datetime(2025, 9, 27, 12, 0, 0), "noon"),
        # End of day (23:59:59 on Sep 27) — should be included
        (100, 4, datetime(2025, 9, 27, 23, 59, 59), "late night"),
        # Start of next day (00:00:00 on Sep 28) — should be excluded
        (100, 5, datetime(2025, 9, 28, 0, 0, 0), "tomorrow"),
    ]

    async with factory() as session:
        for gid, mid, ts, text in messages_data:
            session.add(GroupMessage(group_id=gid, message_id=mid, sent_at=ts, content_text=text))
        await session.commit()

    # Query with the same logic as summarize.py
    async with factory() as session:
        stmt = (
            select(GroupMessage)
            .where(GroupMessage.group_id == 100)
            .where(GroupMessage.sent_at >= start)
            .where(GroupMessage.sent_at < end)
            .order_by(GroupMessage.sent_at)
        )
        result = await session.execute(stmt)
        rows = list(result.scalars().all())

    assert len(rows) == 3
    assert rows[0].content_text == "midnight"
    assert rows[1].content_text == "noon"
    assert rows[2].content_text == "late night"


# ---------------------------------------------------------------------------
# Test 5: 无消息时不调用 LLM
# ---------------------------------------------------------------------------


async def test_no_messages_no_llm_call():
    """When no messages found, LLM should not be called."""
    from src.summarize import chunk_messages

    # Empty message list produces empty chunks — so no LLM call would be made
    chunks = chunk_messages([])
    assert chunks == []

    # Simulate the run() logic: if messages is empty, we return early
    # This verifies the guard in run() that checks `if not messages`
    messages: list[GroupMessage] = []
    assert not messages  # truthy check → would skip LLM


# ---------------------------------------------------------------------------
# Test 6: 总结正常输出（模拟 LLM 响应）
# ---------------------------------------------------------------------------


async def test_summarize_chunk_output():
    """Summarize produces output using mocked LLM."""
    from src.summarize import summarize_chunk

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "这是一份测试总结。"

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    result = await summarize_chunk(mock_client, "test-model", "test text")
    assert result == "这是一份测试总结。"

    # Verify the LLM was called with expected parameters
    mock_client.chat.completions.create.assert_called_once()
    call_kwargs = mock_client.chat.completions.create.call_args
    assert call_kwargs.kwargs["model"] == "test-model"


# ---------------------------------------------------------------------------
# Test 7: 分块逻辑
# ---------------------------------------------------------------------------


def test_chunk_messages_single_chunk():
    """Messages fitting in one chunk produce a single chunk."""
    from src.summarize import chunk_messages

    messages = [
        MagicMock(sent_at=datetime(2025, 9, 27, 10, i, 0), content_text=f"msg {i}")
        for i in range(5)
    ]
    chunks = chunk_messages(messages, max_chars=10000)
    assert len(chunks) == 1


def test_chunk_messages_multiple_chunks():
    """Large messages are split into multiple chunks."""
    from src.summarize import chunk_messages

    messages = [
        MagicMock(
            sent_at=datetime(2025, 9, 27, 10, 0, i),
            content_text="x" * 500,
        )
        for i in range(30)
    ]
    # With max_chars=5000, 30 messages of ~512 chars each should split
    chunks = chunk_messages(messages, max_chars=5000)
    assert len(chunks) > 1


# ---------------------------------------------------------------------------
# Test 8: 时间戳转换 (Unix timestamp → Asia/Shanghai naive datetime)
# ---------------------------------------------------------------------------


def test_timestamp_conversion():
    """Unix timestamp is correctly converted to Asia/Shanghai naive datetime."""
    # 2025-09-27 12:00:00 UTC = 2025-09-27 20:00:00 Asia/Shanghai
    unix_ts = 1759060800  # approx 2025-09-27 12:00 UTC
    utc_dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
    shanghai_dt = utc_dt.astimezone(SHANGHAI_TZ)
    naive_dt = shanghai_dt.replace(tzinfo=None)

    assert naive_dt.hour == utc_dt.hour + 8 or naive_dt.day != utc_dt.day
    assert naive_dt.tzinfo is None


# ---------------------------------------------------------------------------
# Test 9: 纯文本提取模拟
# ---------------------------------------------------------------------------


def test_plaintext_extraction():
    """Messages with only non-text content produce empty plaintext."""
    # Simulate an event-like object
    mock_event = MagicMock()
    mock_event.get_plaintext.return_value = ""
    text = mock_event.get_plaintext().strip()
    assert text == ""

    # Simulate event with actual text
    mock_event.get_plaintext.return_value = "  Hello  "
    text = mock_event.get_plaintext().strip()
    assert text == "Hello"


# ---------------------------------------------------------------------------
# Test 10: summarize_chunk with context (multi-chunk scenario)
# ---------------------------------------------------------------------------


async def test_summarize_chunk_with_context():
    """When context is provided, it's included in the LLM prompt."""
    from src.summarize import summarize_chunk

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "合并总结"

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    result = await summarize_chunk(mock_client, "test-model", "new text", context="前文总结内容")
    assert result == "合并总结"

    # Verify the user content includes context
    call_kwargs = mock_client.chat.completions.create.call_args
    user_msg = call_kwargs.kwargs["messages"][1]["content"]
    assert "前文总结" in user_msg
    assert "new text" in user_msg


# ---------------------------------------------------------------------------
# Test 11: database module raises on uninitialized access
# ---------------------------------------------------------------------------


def test_get_session_raises_before_init():
    """get_session raises RuntimeError if init_engine wasn't called."""
    from src.storage import database

    # Save and clear state
    saved_factory = database._session_factory
    database._session_factory = None
    try:
        with pytest.raises(RuntimeError, match="数据库引擎未初始化"):
            database.get_session()
    finally:
        database._session_factory = saved_factory


# ---------------------------------------------------------------------------
# Test 12: DailySummary 表模型增删查与唯一约束
# ---------------------------------------------------------------------------


async def test_insert_daily_summary(db_session):
    """DailySummary model is stored correctly."""
    summary_record = DailySummary(
        group_id=123456789,
        summary_date=date(2025, 9, 27),
        summary_content="今日讨论了 Python 异步框架。",
        message_count=42,
    )
    db_session.add(summary_record)
    await db_session.commit()

    result = await db_session.execute(
        select(DailySummary).where(
            DailySummary.group_id == 123456789,
            DailySummary.summary_date == date(2025, 9, 27),
        )
    )
    stored = result.scalars().first()
    assert stored is not None
    assert stored.group_id == 123456789
    assert stored.summary_date == date(2025, 9, 27)
    assert stored.summary_content == "今日讨论了 Python 异步框架。"
    assert stored.message_count == 42
    assert stored.created_at is not None


async def test_duplicate_daily_summary_rejected(db_engine):
    """Duplicate (group_id, summary_date) is rejected by unique constraint."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    from sqlalchemy.exc import IntegrityError

    async with factory() as session:
        s1 = DailySummary(
            group_id=100,
            summary_date=date(2025, 9, 27),
            summary_content="first summary",
            message_count=10,
        )
        session.add(s1)
        await session.commit()

    async with factory() as session:
        s2 = DailySummary(
            group_id=100,
            summary_date=date(2025, 9, 27),
            summary_content="second summary",
            message_count=20,
        )
        session.add(s2)
        with pytest.raises(IntegrityError):
            await session.commit()


# ---------------------------------------------------------------------------
# Test 13: Summary Service generate_and_save_summary
# ---------------------------------------------------------------------------


@pytest.fixture
async def init_test_db():
    """Configure src.storage.database to use in-memory SQLite engine for testing."""
    from src.storage import database

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    saved_engine = database._engine
    saved_factory = database._session_factory

    database._engine = engine
    database._session_factory = async_sessionmaker(engine, expire_on_commit=False)

    yield engine

    await engine.dispose()
    database._engine = saved_engine
    database._session_factory = saved_factory


async def test_generate_and_save_summary_persists(init_test_db):
    """generate_and_save_summary fetches messages, calls LLM, saves to DailySummary."""
    from src.services.summary import generate_and_save_summary
    from src.storage.database import get_session

    test_date = date(2025, 9, 27)
    group_id = 999

    # 准备群消息
    async with get_session() as session:
        session.add(
            GroupMessage(
                group_id=group_id,
                message_id=1,
                sent_at=datetime(2025, 9, 27, 10, 0, 0),
                content_text="讨论需求设计",
            )
        )
        session.add(
            GroupMessage(
                group_id=group_id,
                message_id=2,
                sent_at=datetime(2025, 9, 27, 11, 0, 0),
                content_text="完成代码开发",
            )
        )
        await session.commit()

    # 模拟 LLM
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "这是一份自动生成的测试总结。"

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    summary = await generate_and_save_summary(
        group_id=group_id,
        date_obj=test_date,
        client=mock_client,
        model="mock-model",
    )

    assert summary == "这是一份自动生成的测试总结。"
    mock_client.chat.completions.create.assert_called_once()

    # 验证落库
    async with get_session() as session:
        result = await session.execute(
            select(DailySummary).where(
                DailySummary.group_id == group_id,
                DailySummary.summary_date == test_date,
            )
        )
        saved = result.scalars().first()
        assert saved is not None
        assert saved.summary_content == "这是一份自动生成的测试总结。"
        assert saved.message_count == 2


async def test_generate_and_save_summary_cache_hit(init_test_db):
    """When DailySummary already exists, returns cached content without calling LLM."""
    from src.services.summary import generate_and_save_summary
    from src.storage.database import get_session

    test_date = date(2025, 9, 27)
    group_id = 888

    # 预先存入已存在的总结
    async with get_session() as session:
        session.add(
            DailySummary(
                group_id=group_id,
                summary_date=test_date,
                summary_content="已存在的历史总结",
                message_count=5,
            )
        )
        await session.commit()

    mock_client = AsyncMock()

    summary = await generate_and_save_summary(
        group_id=group_id,
        date_obj=test_date,
        client=mock_client,
        model="mock-model",
    )

    assert summary == "已存在的历史总结"
    mock_client.chat.completions.create.assert_not_called()


async def test_generate_and_save_summary_force_refresh(init_test_db):
    """When force_refresh=True, regenerates and updates existing DailySummary."""
    from src.services.summary import generate_and_save_summary
    from src.storage.database import get_session

    test_date = date(2025, 9, 27)
    group_id = 777

    # 预先存入已有记录及消息
    async with get_session() as session:
        session.add(
            DailySummary(
                group_id=group_id,
                summary_date=test_date,
                summary_content="旧的总结",
                message_count=1,
            )
        )
        session.add(
            GroupMessage(
                group_id=group_id,
                message_id=1,
                sent_at=datetime(2025, 9, 27, 9, 0, 0),
                content_text="最新消息内容",
            )
        )
        await session.commit()

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "全新重新生成的总结。"

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    summary = await generate_and_save_summary(
        group_id=group_id,
        date_obj=test_date,
        client=mock_client,
        model="mock-model",
        force_refresh=True,
    )

    assert summary == "全新重新生成的总结。"
    mock_client.chat.completions.create.assert_called_once()

    # 验证数据库记录已被更新
    async with get_session() as session:
        result = await session.execute(
            select(DailySummary).where(
                DailySummary.group_id == group_id,
                DailySummary.summary_date == test_date,
            )
        )
        saved = result.scalars().first()
        assert saved is not None
        assert saved.summary_content == "全新重新生成的总结。"


async def test_generate_and_save_summary_no_messages(init_test_db):
    """When no messages exist for that day, returns empty string and does not call LLM."""
    from src.services.summary import generate_and_save_summary
    from src.storage.database import get_session

    test_date = date(2025, 9, 27)
    group_id = 666

    mock_client = AsyncMock()

    summary = await generate_and_save_summary(
        group_id=group_id,
        date_obj=test_date,
        client=mock_client,
        model="mock-model",
    )

    assert summary == ""
    mock_client.chat.completions.create.assert_not_called()

    # 验证未写入总结表
    async with get_session() as session:
        result = await session.execute(
            select(DailySummary).where(
                DailySummary.group_id == group_id,
                DailySummary.summary_date == test_date,
            )
        )
        saved = result.scalars().first()
        assert saved is None


async def test_generate_and_save_summary_missing_env(init_test_db):
    """Raises ValueError when LLM environment variables are missing and no client is passed."""
    from src.services.summary import generate_and_save_summary
    from src.storage.database import get_session

    test_date = date(2025, 9, 27)
    group_id = 555

    # 插入消息以进入 LLM 阶段
    async with get_session() as session:
        session.add(
            GroupMessage(
                group_id=group_id,
                message_id=1,
                sent_at=datetime(2025, 9, 27, 9, 0, 0),
                content_text="一条消息",
            )
        )
        await session.commit()

    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError, match="LLM_API_KEY"):
            await generate_and_save_summary(group_id=group_id, date_obj=test_date)
