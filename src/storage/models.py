from datetime import date, datetime, timedelta, timezone

from sqlalchemy import BigInteger, Date, DateTime, Integer, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SHANGHAI_TZ = timezone(timedelta(hours=8))


def get_shanghai_now() -> datetime:
    return datetime.now(SHANGHAI_TZ).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class GroupMessage(Base):
    __tablename__ = "group_messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (UniqueConstraint("group_id", "message_id", name="uq_group_message"),)


class DailySummary(Base):
    __tablename__ = "daily_summaries"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    summary_date: Mapped[date] = mapped_column(Date, nullable=False)
    summary_content: Mapped[str] = mapped_column(Text, nullable=False)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=get_shanghai_now)

    __table_args__ = (
        UniqueConstraint("group_id", "summary_date", name="uq_group_summary_date"),
    )
