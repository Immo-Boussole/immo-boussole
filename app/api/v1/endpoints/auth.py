import hashlib
import secrets
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db

router = APIRouter()

@router.post("/login", response_model=schemas.LoginResponse)
def login_api(
    request: Request,
    credentials: schemas.LoginRequest,
    db: Session = Depends(get_db)
):
    """
    Authenticate a user via username and password.
    Returns an API key (Bearer token) for browser extensions / API integrations.
    """
    user = db.query(models.User).filter(models.User.username == credentials.username).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identifiants invalides"
        )

    pwd_hash_600k = hashlib.pbkdf2_hmac('sha256', credentials.password.encode('utf-8'), user.salt, 600000)
    pwd_hash_100k = hashlib.pbkdf2_hmac('sha256', credentials.password.encode('utf-8'), user.salt, 100000)

    if user.password_hash not in (pwd_hash_600k, pwd_hash_100k):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identifiants invalides"
        )

    # Generate or refresh API key for the user
    raw_key = secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    user.api_key_hash = key_hash
    user.can_create_api_key = True
    db.commit()

    return schemas.LoginResponse(
        api_key=raw_key,
        token_type="bearer",
        username=user.username,
        role=user.role,
        message="Connexion réussie"
    )
