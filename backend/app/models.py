from datetime import datetime, timezone

from sqlalchemy import JSON, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Campaign(Base):
    __tablename__ = 'campaigns'
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(255))
    streams: Mapped[list['Stream']] = relationship(cascade='all, delete-orphan', order_by='Stream.position')


class Stream(Base):
    __tablename__ = 'streams'
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    campaign_id: Mapped[int] = mapped_column(ForeignKey('campaigns.id', ondelete='CASCADE'), index=True)
    name: Mapped[str] = mapped_column(String(255))
    position: Mapped[int] = mapped_column(Integer, default=0)
    editable: Mapped[bool] = mapped_column(default=False)
    # Two complete association snapshots make Cancel atomic, including removed offers.
    baseline: Mapped[list] = mapped_column(JSON, default=list)
    draft: Mapped[list] = mapped_column(JSON, default=list)
    version: Mapped[int] = mapped_column(default=1)
    updated_at: Mapped[str] = mapped_column(String(40), default=lambda: datetime.now(timezone.utc).isoformat())
    __mapper_args__ = {'version_id_col': version}

