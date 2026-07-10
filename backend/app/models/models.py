from sqlalchemy import (
    Column, String, Float, Boolean, Integer,
    DateTime, JSON, ForeignKey, Text, Index
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from app.database import Base


class App(Base):
    """
    Represents a client's application registered on the platform.
    Every client who installs your SDK gets one of these.
    """
    __tablename__ = "apps"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    owner_email = Column(String(255), nullable=False)
    api_key = Column(String(255), unique=True,
                     nullable=False)  # SDK auth token
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    is_active = Column(Boolean, default=True)

    # Relationships
    events = relationship("Event", back_populates="app")
    users = relationship("TrackedUser", back_populates="app")
    insights = relationship("Insight", back_populates="app")


class TrackedUser(Base):
    """
    Represents an end-user of a client's app.
    This is NOT your platform user — it's their user.
    Updated continuously as events come in.
    """
    __tablename__ = "tracked_users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    app_id = Column(UUID(as_uuid=True), ForeignKey("apps.id"), nullable=False)
    # hashed ID from client's app
    user_id = Column(String(255), nullable=False)
    first_seen = Column(DateTime(timezone=True), server_default=func.now())
    last_seen = Column(DateTime(timezone=True), server_default=func.now())
    session_count = Column(Integer, default=0)
    total_events = Column(Integer, default=0)
    onboarding_completed = Column(Boolean, default=False)
    onboarding_step_reached = Column(Integer, default=0)
    days_since_last_session = Column(Float, default=0)
    key_features_used = Column(JSON, default=list)   # ["dashboard", "export"]
    # 0.0 - 1.0, null until enough data
    churn_risk_score = Column(Float, nullable=True)
    # "low", "medium", "high"
    churn_risk_tier = Column(String(10), nullable=True)
    country = Column(String(100), nullable=True)
    device_type = Column(String(50), nullable=True)

    # Relationships
    app = relationship("App", back_populates="users")
    events = relationship("Event", back_populates="tracked_user")

    # Indexes for fast querying
    __table_args__ = (
        Index("ix_tracked_users_app_id", "app_id"),
        Index("ix_tracked_users_churn_tier", "churn_risk_tier"),
        Index("ix_tracked_users_last_seen", "last_seen"),
    )


class Event(Base):
    """
    The raw event stream. Every user action lands here.
    This table will grow fast — indexes are critical.
    """
    __tablename__ = "events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    app_id = Column(UUID(as_uuid=True), ForeignKey("apps.id"), nullable=False)
    tracked_user_id = Column(UUID(as_uuid=True), ForeignKey(
        "tracked_users.id"), nullable=False)
    session_id = Column(String(255), nullable=False)
    event_name = Column(String(255), nullable=False)   # "button_clicked"
    # "engagement", "onboarding" etc
    event_category = Column(String(100), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    properties = Column(JSON, default=dict)  # page, element, feature
    context = Column(JSON, default=dict)     # device, browser, country

    # Relationships
    app = relationship("App", back_populates="events")
    tracked_user = relationship("TrackedUser", back_populates="events")

    __table_args__ = (
        Index("ix_events_app_id", "app_id"),
        Index("ix_events_session_id", "session_id"),
        Index("ix_events_timestamp", "timestamp"),
        Index("ix_events_event_name", "event_name"),
        Index("ix_events_category", "event_category"),
    )


class Insight(Base):
    """
    AI-generated insights stored after pattern detection runs.
    We store them so we're not hitting the AI API on every dashboard load.
    """
    __tablename__ = "insights"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    app_id = Column(UUID(as_uuid=True), ForeignKey("apps.id"), nullable=False)
    # "churn_risk", "dead_feature", "friction_point"
    insight_type = Column(String(100), nullable=False)
    # "critical", "warning", "info"
    severity = Column(String(20), nullable=False)
    title = Column(String(255), nullable=False)
    # The plain English explanation
    body = Column(Text, nullable=False)
    # The pattern data that triggered it
    raw_data = Column(JSON, default=dict)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    app = relationship("App", back_populates="insights")

    __table_args__ = (
        Index("ix_insights_app_id", "app_id"),
        Index("ix_insights_severity", "severity"),
        Index("ix_insights_is_read", "is_read"),
    )


class Session(Base):
    """
    Aggregated session records built from raw events.
    Faster to query than reconstructing sessions from the event stream each time.
    """
    __tablename__ = "sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    app_id = Column(UUID(as_uuid=True), ForeignKey("apps.id"), nullable=False)
    tracked_user_id = Column(UUID(as_uuid=True), ForeignKey(
        "tracked_users.id"), nullable=False)
    session_id = Column(String(255), unique=True, nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    event_count = Column(Integer, default=0)
    pages_visited = Column(JSON, default=list)
    # last page before session ended
    exit_page = Column(String(255), nullable=True)

    __table_args__ = (
        Index("ix_sessions_app_id", "app_id"),
        Index("ix_sessions_tracked_user_id", "tracked_user_id"),
        Index("ix_sessions_started_at", "started_at"),
    )
