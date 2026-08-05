import uuid
import json
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, Text, JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

class Route(Base):
    __tablename__ = "routes"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    bus_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("buses.id", ondelete="SET NULL"), nullable=True)
    driver_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("drivers.id", ondelete="SET NULL"), nullable=True)
    start_location: Mapped[str] = mapped_column(String(255), nullable=False)
    end_location: Mapped[str] = mapped_column(String(255), nullable=False)
    waypoints: Mapped[dict] = mapped_column(JSON, default=list)
    scheduled_start_time: Mapped[str] = mapped_column(String(50), nullable=True)
    scheduled_end_time: Mapped[str] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="planned")  # planned, in_progress, completed, cancelled
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    bus = relationship("Bus", back_populates="routes")
    driver = relationship("Driver", back_populates="routes")
    students = relationship("Student", back_populates="route")
