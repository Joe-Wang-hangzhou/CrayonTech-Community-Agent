from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


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
