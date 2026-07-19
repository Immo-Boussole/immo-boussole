import hashlib
from datetime import datetime, timezone
from fastapi import Request, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from typing import Optional

from app import models
from app.database import get_db

security = HTTPBearer(auto_error=False)

def get_current_user_api(
    request: Request,
    auth: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db)
) -> models.User:
    """
    Returns the current User.
    Supports both Session Cookie (for web UI) and API Key (Bearer Token, for MCP/tests).
    """
    # 1. Try Session Cookie first
    if request.session.get("authenticated") is True:
        username = request.session.get("username")
        if username:
            user = db.query(models.User).filter(models.User.username == username).first()
            if user:
                return user

    # 2. Try API Key
    if auth and auth.credentials:
        token = auth.credentials
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        user = db.query(models.User).filter(models.User.api_key_hash == token_hash).first()
        if user:
            # Update last used date
            user.api_key_last_used = datetime.now(timezone.utc)
            db.commit()
            return user
            
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )

def get_current_admin_api(
    current_user: models.User = Depends(get_current_user_api)
) -> models.User:
    """
    Ensures the current user is an admin.
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")
    return current_user
