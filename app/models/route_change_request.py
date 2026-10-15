import uuid
from datetime import datetime, timezone, date
from sqlalchemy import String, DateTime, Date, ForeignKey, UUID, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

class RouteChangeRequest(Base):
    __tablename__ = "route_change_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'cancelled')",
            name="check_route_change_status"
        ),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    student_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True)
    requested_by: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    target_route_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("routes.id", ondelete="CASCADE"), nullable=False, index=True)
    target_bus_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("buses.id", ondelete="SET NULL"), nullable=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    end_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    reviewed_by: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("profiles.id", ondelete="SET NULL"), nullable=True)
    review_notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    student = relationship("Student")
    requester = relationship("Profile", foreign_keys=[requested_by])
    target_route = relationship("Route", foreign_keys=[target_route_id])
    target_bus = relationship("Bus", foreign_keys=[target_bus_id])
    reviewer = relationship("Profile", foreign_keys=[reviewed_by])
