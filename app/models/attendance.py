import uuid
from datetime import datetime, timezone, date
from sqlalchemy import String, DateTime, Date, ForeignKey, UUID, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

class Attendance(Base):
    __tablename__ = "attendance"
    __table_args__ = (
        UniqueConstraint("student_id", "attendance_date", "action_type", name="uq_attendance_student_date_action"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    student_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    bus_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("buses.id", ondelete="SET NULL"), nullable=True)
    route_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("routes.id", ondelete="SET NULL"), nullable=True)
    attendance_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)  # 'present', 'absent'
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)  # 'pickup', 'dropoff'
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    scanned_by: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("profiles.id", ondelete="SET NULL"), nullable=True)
    location_lat: Mapped[float | None] = mapped_column(nullable=True)
    location_lng: Mapped[float | None] = mapped_column(nullable=True)

    student = relationship("Student")
    bus = relationship("Bus")
    route = relationship("Route")
    scanner = relationship("Profile")
