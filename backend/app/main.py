from fastapi import FastAPI, Header, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import secrets
import jwt

# Import your database and routers
from app.database import get_db
from app.models.db_models import App
from app.routers import events, insights, dashboard, auth

# 1. CREATE THE APP FIRST
app = FastAPI(
    title="AppScope API",
    description="Behind the scenes brain for app builders",
    version="0.1.0"
)

# 2. ADD MIDDLEWARE
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 3. SETTINGS & AUTH SETUP
# Make sure this matches your auth.py secret!
SECRET_KEY = "your-super-secret-jwt-key"
ALGORITHM = "HS256"

# Helper to get the current user from the token


def get_current_user_email(authorization: str = Header(...)):
    try:
        # Expecting "Bearer <token>"
        token = authorization.split(" ")[1]
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        if email is None:
            raise HTTPException(
                status_code=401, detail="Invalid authentication credentials")
        return email
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

# ==========================================
# GET CURRENT API KEY
# ==========================================


@app.get("/api/settings/api-key")
def get_api_key(email: str = Depends(get_current_user_email), db: Session = Depends(get_db)):
    app_record = db.query(App).filter(App.owner_email == email).first()
    if not app_record:
        raise HTTPException(status_code=404, detail="App not found")

    return {"api_key": app_record.api_key}

# ==========================================
# REGENERATE API KEY
# ==========================================


@app.post("/api/settings/regenerate-key")
def regenerate_api_key(email: str = Depends(get_current_user_email), db: Session = Depends(get_db)):
    app_record = db.query(App).filter(App.owner_email == email).first()
    if not app_record:
        raise HTTPException(status_code=404, detail="App not found")

    # Generate a fresh key
    new_api_key = f"as_live_{secrets.token_hex(16)}"
    app_record.api_key = new_api_key

    db.commit()
    db.refresh(app_record)

    return {"message": "API key regenerated", "api_key": new_api_key}

# 4. BASE ROUTES


@app.get("/")
def root():
    return {"status": "AppScope API is running"}


@app.get("/health")
def health_check():
    return {"status": "awake and tracking!"}


# 5. INCLUDE EXTERNAL ROUTERS
app.include_router(events.router)
app.include_router(insights.router)
app.include_router(dashboard.router)
app.include_router(auth.router)
