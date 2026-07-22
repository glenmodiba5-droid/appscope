from urllib import response
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import get_db
from app.models.db_models import App, Insight
from datetime import datetime, timezone
import httpx
import os
import jwt

router = APIRouter(prefix="/insights", tags=["Insights"])

# JWT Configuration (Must match auth.py)
SECRET_KEY = "your-super-secret-jwt-key"
ALGORITHM = "HS256"

# ── Auth helper ───────────────────────────────────────────────────────────────


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
                               email).first()
    if not app:
        raise HTTPException(
            status_code=404, detail="App not found for this user")

    return app


# ── Pattern 1: Churn Risk ─────────────────────────────────────────────────────
def detect_churn_risk(db: Session, app_id):
    result = db.execute(text("""
        SELECT
            user_id,
            first_seen,
            last_seen,
            session_count,
            onboarding_completed,
            onboarding_step_reached,
            days_since_last_session
        FROM tracked_users
        WHERE app_id = :app_id
          AND onboarding_completed = false
          AND last_seen < NOW() - INTERVAL '7 days'
        ORDER BY last_seen ASC
        LIMIT 100
    """), {"app_id": str(app_id)})
    return result.mappings().all()


# ── Pattern 2: Dead Features ──────────────────────────────────────────────────
def detect_dead_features(db: Session, app_id):
    result = db.execute(text("""
        WITH total_users AS (
            SELECT COUNT(DISTINCT user_id) as total
            FROM tracked_users
            WHERE app_id = :app_id
        ),
        feature_usage AS (
            SELECT
                properties->>'feature' as feature,
                COUNT(DISTINCT tracked_user_id) as user_count
            FROM events
            WHERE app_id = :app_id
              AND properties->>'feature' IS NOT NULL
            GROUP BY properties->>'feature'
        )
        SELECT
            f.feature,
            f.user_count,
            t.total as total_users,
            ROUND((f.user_count::decimal / NULLIF(t.total, 0)) * 100, 2) as usage_pct
        FROM feature_usage f
        CROSS JOIN total_users t
        WHERE (f.user_count::decimal / NULLIF(t.total, 0)) < 0.05
        ORDER BY usage_pct ASC
    """), {"app_id": str(app_id)})
    return result.mappings().all()


# ── Pattern 3: Friction Points ────────────────────────────────────────────────
def detect_friction_points(db: Session, app_id):
    result = db.execute(text("""
        SELECT
            exit_page,
            COUNT(*) as session_exits,
            AVG(duration_seconds) as avg_session_duration
        FROM sessions
        WHERE app_id = :app_id
          AND duration_seconds <= 60
          AND exit_page IS NOT NULL
        GROUP BY exit_page
        ORDER BY session_exits DESC
        LIMIT 10
    """), {"app_id": str(app_id)})
    return result.mappings().all()


# ── Pattern 4: Onboarding Drop-off ───────────────────────────────────────────
def detect_onboarding_dropoff(db: Session, app_id):
    result = db.execute(text("""
        SELECT
            onboarding_step_reached,
            COUNT(*) as users_stopped_here
        FROM tracked_users
        WHERE app_id = :app_id
          AND onboarding_completed = false
          AND onboarding_step_reached > 0
        GROUP BY onboarding_step_reached
        ORDER BY onboarding_step_reached ASC
    """), {"app_id": str(app_id)})
    return result.mappings().all()


# ── AI Narration ──────────────────────────────────────────────────────────────
async def narrate_with_ai(pattern_type: str, raw_data: list) -> str:
    if not raw_data:
        return None

    prompts = {
        "churn_risk": f"""
            You are an AI product analyst. Based on this user behavior data, write a 
            concise, plain English insight (2-3 sentences max) for an app founder.
            Be specific, actionable, and direct. No fluff.
            
            Pattern: Users who never completed onboarding and haven't returned in 7+ days.
            Data: {raw_data}
            
            Format: Start with the key finding, then give one specific recommendation.
        """,
        "dead_features": f"""
            You are an AI product analyst. Based on this feature usage data, write a 
            concise, plain English insight (2-3 sentences max) for an app founder.
            Be specific, actionable, and direct. No fluff.
            
            Pattern: Features with very low adoption rates.
            Data: {raw_data}
            
            Format: Start with the key finding, then give one specific recommendation.
        """,
        "friction_points": f"""
            You are an AI product analyst. Based on this session data, write a 
            concise, plain English insight (2-3 sentences max) for an app founder.
            Be specific, actionable, and direct. No fluff.
            
            Pattern: Pages where users leave within 60 seconds.
            Data: {raw_data}
            
            Format: Start with the key finding, then give one specific recommendation.
        """,
        "onboarding_dropoff": f"""
            You are an AI product analyst. Based on this onboarding data, write a 
            concise, plain English insight (2-3 sentences max) for an app founder.
            Be specific, actionable, and direct. No fluff.
            
            Pattern: Onboarding steps where users stop and never complete setup.
            Data: {raw_data}
            
            Format: Start with the key finding, then give one specific recommendation.
        """
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "Content-Type": "application/json",
                "x-api-key": os.getenv("ANTHROPIC_API_KEY"),
                "anthropic-version": "2023-06-01"
            },
            json={
                "model": "claude-3-5-sonnet-20240620",  # Corrected to a valid Claude model ID
                "max_tokens": 1000,
                "messages": [
                    {"role": "user", "content": prompts[pattern_type]}
                ]
            },
            timeout=30.0
        )

    data = response.json()

    if "content" not in data:
        print(f"Claude API error: {data}")
        # Fallback: generate a basic insight without AI
        fallbacks = {
            "churn_risk": f"{len(raw_data)} users never completed onboarding and haven't returned in 7+ days. Consider sending a re-engagement email or simplifying your onboarding flow.",
            "dead_features": f"{len(raw_data)} features have very low adoption (under 5% of users). Consider removing or redesigning them to reduce UI clutter.",
            "friction_points": f"{len(raw_data)} pages are causing users to leave within 60 seconds. Review these pages for confusing layouts or slow load times.",
            "onboarding_dropoff": f"Users are dropping off during onboarding. Review the steps with the highest abandonment and simplify or remove them.",
        }
        return fallbacks.get(pattern_type, "Pattern detected but AI narration unavailable.")

    return data["content"][0]["text"]

# ── Main endpoint: run all patterns + generate insights ───────────────────────


@router.post("/analyze", status_code=201)
async def analyze(
    app: App = Depends(get_app_from_token),
    db: Session = Depends(get_db)
):
    patterns = {
        "churn_risk": detect_churn_risk(db, app.id),
        "dead_features": detect_dead_features(db, app.id),
        "friction_points": detect_friction_points(db, app.id),
        "onboarding_dropoff": detect_onboarding_dropoff(db, app.id),
    }

    severity_map = {
        "churn_risk": "critical",
        "friction_points": "critical",
        "onboarding_dropoff": "warning",
        "dead_features": "info",
    }

    titles = {
        "churn_risk": "Churn Risk Detected",
        "dead_features": "Low Adoption Features",
        "friction_points": "Friction Points Found",
        "onboarding_dropoff": "Onboarding Drop-off",
    }

    generated = []

    for pattern_type, raw_data in patterns.items():
        raw_list = [dict(row) for row in raw_data]
        if not raw_list:
            continue

        # Convert non-serializable types
        from decimal import Decimal
        for item in raw_list:
            for k, v in item.items():
                if isinstance(v, datetime):
                    item[k] = v.isoformat()
                elif isinstance(v, Decimal):
                    item[k] = float(v)

        ai_body = await narrate_with_ai(pattern_type, raw_list)
        if not ai_body:
            continue

        # --- UPSERT LOGIC STARTS HERE ---
        existing_insight = db.query(Insight).filter(
            Insight.app_id == app.id,
            Insight.insight_type == pattern_type
        ).first()

        if existing_insight:
            existing_insight.body = ai_body
            existing_insight.raw_data = raw_list
            existing_insight.severity = severity_map[pattern_type]
            existing_insight.is_read = False  # Mark unread so it triggers dashboard alerts
            existing_insight.created_at = datetime.now(
                timezone.utc)  # Bump timestamp to now
        else:
            insight = Insight(
                app_id=app.id,
                insight_type=pattern_type,
                severity=severity_map[pattern_type],
                title=titles[pattern_type],
                body=ai_body,
                raw_data=raw_list,
            )
            db.add(insight)
        # --- UPSERT LOGIC ENDS HERE ---

        generated.append({
            "type": pattern_type,
            "severity": severity_map[pattern_type],
            "title": titles[pattern_type],
            "body": ai_body,
            "was_updated": bool(existing_insight)
        })

    db.commit()

    return {
        "status": "ok",
        "insights_processed": len(generated),
        "insights": generated
    }

# ── Fetch stored insights ─────────────────────────────────────────────────────


@router.get("/")
def get_insights(
    app: App = Depends(get_app_from_token),
    db: Session = Depends(get_db)
):
    insights = db.query(Insight).filter(
        Insight.app_id == app.id
    ).order_by(Insight.created_at.desc()).all()

    return {
        "status": "ok",
        "total": len(insights),
        "insights": [
            {
                "id": str(i.id),
                "type": i.insight_type,
                "severity": i.severity,
                "title": i.title,
                "body": i.body,
                "is_read": i.is_read,
                "created_at": i.created_at.isoformat(),
            }
            for i in insights
        ]
    }


@router.post("/cron/analyze-all", tags=["Cron"])
async def cron_analyze_all(
    x_cron_secret: str = Header(..., description="Secret key to trigger cron"),
    db: Session = Depends(get_db)
):
    """Master endpoint to run pattern detection for all active apps."""
    # 1. Verify the secret key
    expected_secret = os.getenv("CRON_SECRET_KEY")
    if not expected_secret or x_cron_secret != expected_secret:
        raise HTTPException(
            status_code=401, detail="Unauthorized cron trigger")

    # 2. Get all active apps
    active_apps = db.query(App).filter(App.is_active == True).all()

    total_insights_generated = 0
    apps_processed = 0

    severity_map = {
        "churn_risk": "critical",
        "friction_points": "critical",
        "onboarding_dropoff": "warning",
        "dead_features": "info",
    }

    titles = {
        "churn_risk": "Churn Risk Detected",
        "dead_features": "Low Adoption Features",
        "friction_points": "Friction Points Found",
        "onboarding_dropoff": "Onboarding Drop-off",
    }

    # 3. Run the loop for each app
    for app in active_apps:
        apps_processed += 1
        patterns = {
            "churn_risk": detect_churn_risk(db, app.id),
            "dead_features": detect_dead_features(db, app.id),
            "friction_points": detect_friction_points(db, app.id),
            "onboarding_dropoff": detect_onboarding_dropoff(db, app.id),
        }

        for pattern_type, raw_data in patterns.items():
            raw_list = [dict(row) for row in raw_data]
            if not raw_list:
                continue

            # Convert non-serializable types
            from decimal import Decimal
            for item in raw_list:
                for k, v in item.items():
                    if isinstance(v, datetime):
                        item[k] = v.isoformat()
                    elif isinstance(v, Decimal):
                        item[k] = float(v)

            ai_body = await narrate_with_ai(pattern_type, raw_list)
            if not ai_body:
                continue

            # UPSERT LOGIC
            existing_insight = db.query(Insight).filter(
                Insight.app_id == app.id,
                Insight.insight_type == pattern_type
            ).first()

            if existing_insight:
                existing_insight.body = ai_body
                existing_insight.raw_data = raw_list
                existing_insight.severity = severity_map[pattern_type]
                existing_insight.is_read = False
                existing_insight.created_at = datetime.now(timezone.utc)
            else:
                insight = Insight(
                    app_id=app.id,
                    insight_type=pattern_type,
                    severity=severity_map[pattern_type],
                    title=titles[pattern_type],
                    body=ai_body,
                    raw_data=raw_list,
                )
                db.add(insight)

            total_insights_generated += 1

    db.commit()

    return {
        "status": "ok",
        "message": "Global analysis complete",
        "apps_processed": apps_processed,
        "total_insights_generated": total_insights_generated
    }
