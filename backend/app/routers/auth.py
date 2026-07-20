from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from passlib.context import CryptContext
import jwt
import datetime
import uuid
import secrets

# Import your database dependency and models
from app.database import get_db
from app.models import App

router = APIRouter(prefix="/auth", tags=["Authentication"])

# 1. Setup Password Hashing & JWT Secret
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = "your-super-secret-jwt-key"  # Change this in production!
ALGORITHM = "HS256"

# 2. Pydantic Schemas from the Frontend HTML


class RegisterRequest(BaseModel):
    # User's personal name (Note: Not currently saved in App model, but received)
    name: str
    email: str      # Maps to owner_email
    password: str   # Will be hashed
    app_name: str   # Maps to App.name


class LoginRequest(BaseModel):
    email: str
    password: str

# 3. Helper Functions


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password):
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: datetime.timedelta = None):
    to_encode = data.copy()
    expire = datetime.datetime.utcnow() + (expires_delta or datetime.timedelta(days=7))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# ==========================================
# REGISTRATION ENDPOINT
# ==========================================


@router.post("/register")
def register(request: RegisterRequest, db: Session = Depends(get_db)):
    # Check if user/app already exists
    existing_app = db.query(App).filter(
        App.owner_email == request.email).first()
    if existing_app:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # Generate new tracking API key (e.g., as_live_...)
    new_api_key = f"as_live_{secrets.token_hex(16)}"

    # Create the new App record
    new_app = App(
        name=request.app_name,
        owner_email=request.email,
        hashed_password=get_password_hash(request.password),
        api_key=new_api_key
    )

    db.add(new_app)
    db.commit()
    db.refresh(new_app)

    # Generate Session Token for the dashboard
    access_token = create_access_token(data={"sub": new_app.owner_email})

    return {
        "message": "Account created successfully",
        "api_key": new_app.api_key,
        "access_token": access_token
    }

# ==========================================
# LOGIN ENDPOINT
# ==========================================


@router.post("/login")
def login(request: LoginRequest, db: Session = Depends(get_db)):
    # Find the app/user by email
    app_record = db.query(App).filter(App.owner_email == request.email).first()

    # Verify existence and password
    if not app_record or not app_record.hashed_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    if not verify_password(request.password, app_record.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    # Generate fresh Session Token
    access_token = create_access_token(data={"sub": app_record.owner_email})

    return {
        "message": "Login successful",
        "access_token": access_token
    }
