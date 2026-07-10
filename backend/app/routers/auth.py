from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import App
from pydantic import BaseModel, EmailStr
import uuid

router = APIRouter(prefix="/auth", tags=["Auth"])


class RegisterPayload(BaseModel):
    name: str
    email: str
    app_name: str


@router.post("/register", status_code=201)
def register(payload: RegisterPayload, db: Session = Depends(get_db)):
    # Check if email already registered
    existing = db.query(App).filter(App.owner_email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=400, detail="Email already registered.")

    api_key = f"as_live_{uuid.uuid4().hex}"

    app = App(
        name=payload.app_name,
        owner_email=payload.email,
        api_key=api_key,
    )
    db.add(app)
    db.commit()
    db.refresh(app)

    return {
        "status": "ok",
        "message": "Account created successfully.",
        "app_name": app.name,
        "owner_email": app.owner_email,
        "api_key": app.api_key,
        "app_id": str(app.id),
    }
