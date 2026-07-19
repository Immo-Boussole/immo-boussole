from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
import secrets
import hashlib
from typing import List

from app import models, schemas
from app.database import get_db
from app.api.deps import get_current_user_api, get_current_admin_api

router = APIRouter()

@router.post("/me/api-key", response_model=schemas.ApiKeyResponse)
def create_my_api_key(
    current_user: models.User = Depends(get_current_user_api),
    db: Session = Depends(get_db)
):
    """
    Generate a new API Key for the current user. 
    Requires `can_create_api_key` right or `admin` role.
    """
    if current_user.role != "admin" and not current_user.can_create_api_key:
        raise HTTPException(status_code=403, detail="You do not have permission to create an API key.")

    raw_key = secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    current_user.api_key_hash = key_hash
    db.commit()

    return schemas.ApiKeyResponse(
        api_key=raw_key,
        message="API Key generated successfully. Please save it now, you won't be able to see it again."
    )

@router.get("/admin", response_model=List[schemas.UserApiMgmtResponse])
def get_users_api_management(
    admin_user: models.User = Depends(get_current_admin_api),
    db: Session = Depends(get_db)
):
    """
    Admin: List all users with their API key status.
    """
    users = db.query(models.User).all()
    results = []
    for u in users:
        results.append(schemas.UserApiMgmtResponse(
            id=u.id,
            username=u.username,
            role=u.role,
            can_create_api_key=u.can_create_api_key,
            has_api_key=u.api_key_hash is not None,
            api_key_last_used=u.api_key_last_used
        ))
    return results

@router.put("/admin/{user_id}/api-rights", response_model=schemas.UserApiMgmtResponse)
def update_user_api_rights(
    user_id: int,
    can_create: bool,
    admin_user: models.User = Depends(get_current_admin_api),
    db: Session = Depends(get_db)
):
    """
    Admin: Grant or revoke the right to create API keys.
    If revoked, existing API key is also destroyed.
    """
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.can_create_api_key = can_create
    if not can_create:
        user.api_key_hash = None # Revoke active key

    db.commit()
    
    return schemas.UserApiMgmtResponse(
        id=user.id,
        username=user.username,
        role=user.role,
        can_create_api_key=user.can_create_api_key,
        has_api_key=user.api_key_hash is not None,
        api_key_last_used=user.api_key_last_used
    )

@router.delete("/admin/{user_id}/api-key")
def revoke_user_api_key(
    user_id: int,
    admin_user: models.User = Depends(get_current_admin_api),
    db: Session = Depends(get_db)
):
    """
    Admin: Revoke a specific user's active API key.
    """
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.api_key_hash = None
    db.commit()
    return {"message": "API Key revoked successfully"}
