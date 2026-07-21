from app.database import SessionLocal
from backend.app.models.db_models import App, TrackedUser, Event, Session as SessionModel
from datetime import datetime, timezone, timedelta
import uuid


def seed():
    db = SessionLocal()

    # Get or create test app
    existing = db.query(App).filter(
        App.owner_email == "test@appscope.com").first()
    if existing:
        app = existing
        print(f"Using existing app. API Key: {app.api_key}")
    else:
        api_key = f"as_live_{uuid.uuid4().hex}"
        app = App(name="Test App",
                  owner_email="test@appscope.com", api_key=api_key)
        db.add(app)
        db.commit()
        db.refresh(app)
        print(f"Created app. API Key: {app.api_key}")

    now = datetime.now(timezone.utc)

    # ── Seed 10 test users ────────────────────────────────────────────────────
    users_data = [
        # (user_id, days_ago_first, days_ago_last, onboarding_done, step_reached)
        ("user_001", 20, 15, False, 1),  # churned at step 1
        ("user_002", 18, 12, False, 2),  # churned at step 2
        ("user_003", 15, 10, False, 2),  # churned at step 2
        ("user_004", 14, 8,  False, 3),  # churned at step 3
        ("user_005", 12, 8,  False, 1),  # churned at step 1
        ("user_006", 10, 1,  True,  4),  # completed onboarding, active
        ("user_007", 9,  2,  True,  4),  # completed onboarding, active
        ("user_008", 8,  1,  True,  4),  # completed onboarding, active
        ("user_009", 7,  9,  False, 2),  # churned at step 2
        ("user_010", 5,  1,  True,  4),  # completed onboarding, active
    ]

    created_users = []

    for uid, days_first, days_last, onboarding_done, step in users_data:
        existing_user = db.query(TrackedUser).filter(
            TrackedUser.app_id == app.id,
            TrackedUser.user_id == uid
        ).first()
        if existing_user:
            created_users.append(existing_user)
            continue

        user = TrackedUser(
            app_id=app.id,
            user_id=uid,
            first_seen=now - timedelta(days=days_first),
            last_seen=now - timedelta(days=days_last),
            session_count=3,
            total_events=10,
            onboarding_completed=onboarding_done,
            onboarding_step_reached=step,
            days_since_last_session=float(days_last),
            key_features_used=["dashboard"] if onboarding_done else [],
            device_type="desktop",
            country="ZA",
        )
        db.add(user)
        db.flush()
        created_users.append(user)

    db.commit()
    print(f"Seeded {len(created_users)} users.")

    # ── Seed sessions with short durations (friction points) ──────────────────
    friction_page = "/pricing"
    for i, user in enumerate(created_users[:5]):
        existing_session = db.query(SessionModel).filter(
            SessionModel.session_id == f"friction_session_{i}"
        ).first()
        if existing_session:
            continue

        session = SessionModel(
            app_id=app.id,
            tracked_user_id=user.id,
            session_id=f"friction_session_{i}",
            started_at=now - timedelta(days=8, hours=i),
            ended_at=now - timedelta(days=8, hours=i, seconds=30),
            duration_seconds=30,  # under 60 seconds — triggers friction detection
            event_count=2,
            pages_visited=[friction_page],
            exit_page=friction_page,
        )
        db.add(session)

    db.commit()
    print("Seeded friction point sessions.")

    # ── Seed events including a dead feature ──────────────────────────────────
    for i, user in enumerate(created_users):
        # Everyone uses dashboard
        e1 = Event(
            app_id=app.id,
            tracked_user_id=user.id,
            session_id=f"seed_session_{i}",
            event_name="page_viewed",
            event_category="engagement",
            timestamp=now - timedelta(days=5, hours=i),
            properties={"page": "/dashboard",
                        "feature": "dashboard", "extra": {}},
            context={"device_type": "desktop", "country": "ZA"},
        )
        db.add(e1)

        # Only 1 out of 10 uses "advanced_reports" — dead feature
        if i == 0:
            e2 = Event(
                app_id=app.id,
                tracked_user_id=user.id,
                session_id=f"seed_session_{i}",
                event_name="page_viewed",
                event_category="engagement",
                timestamp=now - timedelta(days=5, hours=i, minutes=5),
                properties={"page": "/reports/advanced",
                            "feature": "advanced_reports", "extra": {}},
                context={"device_type": "desktop", "country": "ZA"},
            )
            db.add(e2)

    db.commit()
    print("Seeded events.")
    print("Done. Run /insights/analyze now.")


if __name__ == "__main__":
    seed()
