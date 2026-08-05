from datetime import datetime, timezone

from sqlalchemy import DECIMAL, DateTime, ForeignKey, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class GpsLog(Base):
    __tablename__ = "gps_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    bus_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("buses.id", ondelete="CASCADE"), nullable=False
    )
    route_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("routes.id", ondelete="SET NULL"), nullable=True
    )
    latitude: Mapped[float] = mapped_column(DECIMAL(10, 8), nullable=False)
    longitude: Mapped[float] = mapped_column(DECIMAL(11, 8), nullable=False)
    speed: Mapped[float | None] = mapped_column(DECIMAL(5, 2), nullable=True, default=0.0)
    heading: Mapped[float | None] = mapped_column(DECIMAL(5, 2), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    bus = relationship("Bus", back_populates="gps_logs")
    route = relationship("Route", back_populates="gps_logs")
