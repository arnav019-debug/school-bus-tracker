import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

class Student(Base):
    __tablename__ = "students"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    grade: Mapped[str] = mapped_column(String(50), nullable=True)
    parent_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("profiles.id", ondelete="SET NULL"), nullable=True)
    route_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("routes.id", ondelete="SET NULL"), nullable=True)
    pickup_stop: Mapped[str] = mapped_column(String(255), nullable=True)
    dropoff_stop: Mapped[str] = mapped_column(String(255), nullable=True)
    qr_code_id: Mapped[str] = mapped_column(String(100), unique=True, default=lambda: f"QR-{uuid.uuid4().hex[:8].upper()}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    parent = relationship("Profile", back_populates="students")
    route = relationship("Route", back_populates="students")
