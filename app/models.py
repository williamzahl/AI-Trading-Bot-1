"""Databasetabeller."""
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    instrument: Mapped[str | None] = mapped_column(String(64), index=True)
    indicator: Mapped[str | None] = mapped_column(String(128), index=True)
    signal: Mapped[str | None] = mapped_column(String(64))
    price: Mapped[float | None] = mapped_column(Float)
    timeframe: Mapped[str | None] = mapped_column(String(16))
    bar_time: Mapped[str | None] = mapped_column(String(64))
    source_ip: Mapped[str | None] = mapped_column(String(64))
    # NEW -> APPROVED / REJECTED (settes fra Telegram)
    status: Mapped[str] = mapped_column(String(16), default="NEW", index=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    telegram_message_id: Mapped[int | None] = mapped_column(Integer)
    raw: Mapped[dict] = mapped_column(JSON)
    # Ordre til MT5: SENDING / FILLED / FAILED / SKIPPED
    exec_status: Mapped[str | None] = mapped_column(String(16))
    exec_message: Mapped[str | None] = mapped_column(String(512))
    exec_order_id: Mapped[str | None] = mapped_column(String(64))
    exec_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exec_price: Mapped[float | None] = mapped_column(Float)
    exec_lot: Mapped[float | None] = mapped_column(Float)
    exec_sl: Mapped[float | None] = mapped_column(Float)
    exec_tp: Mapped[float | None] = mapped_column(Float)
    # Etter at traden er lukket (meldt av EA-en)
    close_price: Mapped[float | None] = mapped_column(Float)
    close_profit: Mapped[float | None] = mapped_column(Float)
    close_reason: Mapped[str | None] = mapped_column(String(32))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "received_at": self.received_at.isoformat() if self.received_at else None,
            "instrument": self.instrument,
            "indicator": self.indicator,
            "signal": self.signal,
            "price": self.price,
            "timeframe": self.timeframe,
            "bar_time": self.bar_time,
            "status": self.status,
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
            "source_ip": self.source_ip,
            "exec_status": self.exec_status,
            "exec_message": self.exec_message,
            "exec_order_id": self.exec_order_id,
            "exec_price": self.exec_price,
            "exec_sl": self.exec_sl,
            "exec_tp": self.exec_tp,
            "close_price": self.close_price,
            "close_profit": self.close_profit,
            "close_reason": self.close_reason,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
        }


class Setting(Base):
    """Enkle noekkel/verdi-innstillinger, f.eks. hvilken Telegram-chat som eier boten."""
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(512))
