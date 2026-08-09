import uuid
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

class Bus(Base):
    __tablename__ = "buses"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    bus_number: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    license_plate: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="active")  # active, maintenance, out_of_service
    driver_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("drivers.id", ondelete="SET NULL"), nullable=True)
    # The existing Supabase column is a TIMESTAMP WITHOUT TIME ZONE column.
    # Store a matching naive UTC value so asyncpg does not reject inserts.
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    driver = relationship("Driver", back_populates="buses")
    routes = relationship("Route", back_populates="bus")
    gps_logs = relationship("GpsLog", back_populates="bus")
