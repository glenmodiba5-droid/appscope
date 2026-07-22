from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from sqlalchemy import text
import jwt
from app.database import get_db
from app.models.db_models import App, TrackedUser, Insight

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

# JWT Configuration (Must match auth.py)
SECRET_KEY = "your-super-secret-jwt-key"
ALGORITHM = "HS256"


def get_app_from_token(authorization: str = Header(...), db: Session = Depends(get_db)):
    """Decodes the human's JWT token and returns their associated App"""
    try:
        # Extract token from "Bearer <token>"
        token = authorization.split(" ")[1]
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        if not email:
            raise HTTPException(
                status_code=401, detail="Invalid token payload")
    except Exception:
        raise HTTPException(
            status_code=401, detail="Invalid or expired session token")

    app = db.query(App).filter(App.owner_email ==
                               email, App.is_active == True).first()
    if not app:
        raise HTTPException(
            status_code=404, detail="App not found for this user")

    return app


@router.get("/overview")
def get_overview(app: App = Depends(get_app_from_token), db: Session = Depends(get_db)):
    """Main dashboard summary — the first thing a founder sees."""

    # Total users
    total_users = db.query(TrackedUser).filter(
        TrackedUser.app_id == app.id).count()

    # Active last 7 days
    active_7d = db.execute(text("""
        SELECT COUNT(*) FROM tracked_users
        WHERE app_id = :app_id
        AND last_seen >= NOW() - INTERVAL '7 days'
    """), {"app_id": str(app.id)}).scalar()

    # Active last 30 days
    active_30d = db.execute(text("""
        SELECT COUNT(*) FROM tracked_users
        WHERE app_id = :app_id
        AND last_seen >= NOW() - INTERVAL '30 days'
    """), {"app_id": str(app.id)}).scalar()

    # Churn risk users
    churn_risk = db.execute(text("""
        SELECT COUNT(*) FROM tracked_users
        WHERE app_id = :app_id
        AND onboarding_completed = false
        AND last_seen < NOW() - INTERVAL '7 days'
    """), {"app_id": str(app.id)}).scalar()

    # Onboarding completion rate
    completed = db.execute(text("""
        SELECT COUNT(*) FROM tracked_users
        WHERE app_id = :app_id AND onboarding_completed = true
    """), {"app_id": str(app.id)}).scalar()

    completion_rate = round(
        (completed / total_users * 100), 1) if total_users > 0 else 0

    # Unread critical insights
    critical_insights = db.query(Insight).filter(
        Insight.app_id == app.id,
        Insight.severity == "critical",
        Insight.is_read == False
    ).count()

    # Daily active users — last 14 days
    dau = db.execute(text("""
        SELECT
            DATE(last_seen) as date,
            COUNT(DISTINCT user_id) as active_users
        FROM tracked_users
        WHERE app_id = :app_id
        AND last_seen >= NOW() - INTERVAL '14 days'
        GROUP BY DATE(last_seen)
        ORDER BY date ASC
    """), {"app_id": str(app.id)}).mappings().all()

    return {
        "status": "ok",
        "app_name": app.name,
        # <--- CRITICAL: Frontend needs this to generate the track.js snippet!
        "api_key": app.api_key,
        "metrics": {
            "total_users": total_users,
            "active_7d": active_7d,
            "active_30d": active_30d,
            "churn_risk_count": churn_risk,
            "onboarding_completion_rate": completion_rate,
            "unread_critical_insights": critical_insights,
        },
        "daily_active_users": [
            {"date": str(row["date"]), "active_users": row["active_users"]}
            for row in dau
        ]
    }


@router.get("/users/at-risk")
def get_at_risk_users(app: App = Depends(get_app_from_token), db: Session = Depends(get_db)):
    """List of users flagged as churn risks."""
    users = db.execute(text("""
        SELECT
            user_id, first_seen, last_seen, session_count,
            onboarding_step_reached, days_since_last_session,
            country, device_type
        FROM tracked_users
        WHERE app_id = :app_id
        AND onboarding_completed = false
        AND last_seen < NOW() - INTERVAL '7 days'
        ORDER BY last_seen ASC
        LIMIT 50
    """), {"app_id": str(app.id)}).mappings().all()

    return {
        "status": "ok",
        "total_at_risk": len(users),
        "users": [
            {
                "user_id": row["user_id"],
                "first_seen": row["first_seen"].isoformat(),
                "last_seen": row["last_seen"].isoformat(),
                "session_count": row["session_count"],
                "onboarding_step_reached": row["onboarding_step_reached"],
                "days_inactive": round(row["days_since_last_session"], 1),
                "country": row["country"],
                "device_type": row["device_type"],
            }
            for row in users
        ]
    }


@router.get("/retention")
def get_retention(app: App = Depends(get_app_from_token), db: Session = Depends(get_db)):
    """Onboarding funnel and retention breakdown."""
    # Onboarding funnel by step
    funnel = db.execute(text("""
        SELECT
            onboarding_step_reached as step,
            COUNT(*) as users,
            ROUND(COUNT(*) * 100.0 / NULLIF(SUM(COUNT(*)) OVER (), 0), 1) as pct
        FROM tracked_users
        WHERE app_id = :app_id
        AND onboarding_step_reached > 0
        GROUP BY onboarding_step_reached
        ORDER BY step ASC
    """), {"app_id": str(app.id)}).mappings().all()

    # Retention by cohort (week joined)
    retention = db.execute(text("""
        SELECT
            DATE_TRUNC('week', first_seen) as cohort_week,
            COUNT(*) as total,
            SUM(CASE WHEN last_seen >= NOW() - INTERVAL '7 days' THEN 1 ELSE 0 END) as retained
        FROM tracked_users
        WHERE app_id = :app_id
        GROUP BY cohort_week
        ORDER BY cohort_week DESC
        LIMIT 8
    """), {"app_id": str(app.id)}).mappings().all()

    return {
        "status": "ok",
        "onboarding_funnel": [
            {"step": row["step"], "users": row["users"],
                "percentage": float(row["pct"])}
            for row in funnel
        ],
        "weekly_retention": [
            {
                "cohort_week": row["cohort_week"].isoformat(),
                "total_users": row["total"],
                "retained": row["retained"],
                "retention_rate": round(row["retained"] / row["total"] * 100, 1) if row["total"] > 0 else 0
            }
            for row in retention
        ]
    }
