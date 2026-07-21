from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.database import get_db
from backend.app.models.db_models import App, TrackedUser, Event, Session as SessionModel
from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import datetime, timezone
import uuid

router = APIRouter(prefix="/events", tags=["Events"])

# ── Pydantic schemas ────────────────────────────────────────────────────────


class EventProperties(BaseModel):
    page: Optional[str] = None
    element: Optional[str] = None
    feature: Optional[str] = None
    extra: Optional[dict] = {}


class EventContext(BaseModel):
    device_type: Optional[str] = None
    browser: Optional[str] = None
    country: Optional[str] = None
    app_version: Optional[str] = None


class IncomingEvent(BaseModel):
    # NEW: SDK can send its own UUID to prevent duplicates
    event_id: Optional[str] = None
    user_id: str
    session_id: str
    event_name: str
    event_category: str
    timestamp: datetime
    properties: Optional[EventProperties] = EventProperties()
    context: Optional[EventContext] = EventContext()

    @field_validator("event_category")
    @classmethod
    def validate_category(cls, v):
        allowed = {"engagement", "navigation",
                   "error", "conversion", "onboarding"}
        if v not in allowed:
            raise ValueError(f"event_category must be one of {allowed}")
        return v

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError("user_id cannot be empty")
        return v.strip()

# ── Helpers ─────────────────────────────────────────────────────────────────


def get_or_create_user(db: Session, app_id: uuid.UUID, user_id: str, context: EventContext):
    user = db.query(TrackedUser).filter(
        TrackedUser.app_id == app_id,
        TrackedUser.user_id == user_id
    ).first()

    if not user:
        user = TrackedUser(
            app_id=app_id,
            user_id=user_id,
            device_type=context.device_type,
            country=context.country,
        )
        db.add(user)
        db.flush()

    return user


def get_or_create_session(db: Session, app_id: uuid.UUID, user: TrackedUser, event: IncomingEvent):
    session = db.query(SessionModel).filter(
        SessionModel.session_id == event.session_id
    ).first()

    if not session:
        session = SessionModel(
            app_id=app_id,
            tracked_user_id=user.id,
            session_id=event.session_id,
            started_at=event.timestamp,
        )
        db.add(session)
        db.flush()

    return session


def update_user_state(user: TrackedUser, event: IncomingEvent, now: datetime):
    user.last_seen = now
    user.total_events = (user.total_events or 0) + 1

    if event.properties and event.properties.feature:
        features = user.key_features_used or []
        if event.properties.feature not in features:
            features.append(event.properties.feature)
            user.key_features_used = features

    if event.event_category == "onboarding":
        if event.event_name == "onboarding_completed":
            user.onboarding_completed = True
        if event.properties and event.properties.extra:
            step = event.properties.extra.get("step")
            if step and isinstance(step, int):
                if step > (user.onboarding_step_reached or 0):
                    user.onboarding_step_reached = step

    if user.first_seen:
        delta = now - user.first_seen.replace(tzinfo=timezone.utc)
        user.days_since_last_session = round(delta.total_seconds() / 86400, 2)


# ── Main endpoint ───────────────────────────────────────────────────────────

@router.post("/track", status_code=201)
def track_event(
    payload: IncomingEvent,
    x_api_key: str = Header(..., description="Client app API key"),
    db: Session = Depends(get_db)
):
    app = db.query(App).filter(
        App.api_key == x_api_key,
        App.is_active == True
    ).first()

    if not app:
        raise HTTPException(
            status_code=401, detail="Invalid or inactive API key")

    now = datetime.now(timezone.utc)

    user = get_or_create_user(db, app.id, payload.user_id, payload.context)
    session = get_or_create_session(db, app.id, user, payload)

    # Prepare event data, using the client-provided ID if it exists
    event_kwargs = {
        "app_id": app.id,
        "tracked_user_id": user.id,
        "session_id": payload.session_id,
        "event_name": payload.event_name,
        "event_category": payload.event_category,
        "timestamp": payload.timestamp,
        "properties": payload.properties.model_dump(),
        "context": payload.context.model_dump(),
    }

    # If the SDK sent an ID, use it as the database primary key
    if payload.event_id:
        try:
            event_kwargs["id"] = uuid.UUID(payload.event_id)
        except ValueError:
            pass  # If they send a malformed UUID, fallback to letting the DB generate one

    event = Event(**event_kwargs)
    db.add(event)

    session.event_count = (session.event_count or 0) + 1
    session.ended_at = now
    if session.started_at:
        session.duration_seconds = int(
            (now - session.started_at.replace(tzinfo=timezone.utc)).total_seconds()
        )
    if payload.properties and payload.properties.page:
        session.exit_page = payload.properties.page
        pages = session.pages_visited or []
        if payload.properties.page not in pages:
            pages.append(payload.properties.page)
            session.pages_visited = pages

    update_user_state(user, payload, now)

    # 7. Commit everything atomically, but catch duplicate retries
    try:
        db.commit()
    except IntegrityError:
        # A unique constraint failed (meaning this event_id is already in the database)
        db.rollback()
        return {
            "status": "ok",
            "message": "Duplicate event ignored via idempotency key.",
            "event_id": payload.event_id,
            "session_id": session.session_id,
        }

    return {
        "status": "ok",
        "event_id": str(event.id),
        "user_id": str(user.id),
        "session_id": session.session_id,
    }
