"""
Notification endpoints & views for Immo-Boussole.
"""
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.notifications import (
    auto_mark_read_expired_notifications,
    get_unread_notifications_count,
    get_user_notifications_query,
    refresh_standard_user_tasks_notifications,
)

from app.translations import get_text

router = APIRouter()
templates = Jinja2Templates(directory="templates")
templates.env.globals["t"] = get_text

def _get_unread_count_global(request: Request) -> int:
    try:
        from app import database, models
        db = next(database.get_db())
        current_user = None
        if request and hasattr(request, "session") and request.session.get("authenticated") is True:
            username = request.session.get("username")
            if username:
                current_user = db.query(models.User).filter(models.User.username == username).first()
        return get_unread_notifications_count(db, current_user)
    except Exception:
        return 0

templates.env.globals["get_unread_count"] = _get_unread_count_global


# ─── Pydantic Schemas ─────────────────────────────────────────────────────────

class MarkReadRequest(BaseModel):
    notification_ids: List[int]


class DeleteNotificationsRequest(BaseModel):
    notification_ids: List[int]


# ─── Helper for Timeline Period Grouping ──────────────────────────────────────

def _group_notifications_by_period(notifications: list):
    """
    Groups a list of Notification ORM objects into period dicts:
      - "Aujourd'hui"
      - "Hier"
      - "Cette semaine"
      - "Plus ancien"
    """
    now = datetime.now(timezone.utc)
    groups = {
        "today": [],
        "yesterday": [],
        "this_week": [],
        "older": [],
    }

    for n in notifications:
        created = n.created_at
        if created is None:
            groups["older"].append(n)
            continue

        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)

        delta = now - created
        days = delta.days

        if days == 0 and created.date() == now.date():
            groups["today"].append(n)
        elif days <= 1 and (now.date() - created.date()).days == 1:
            groups["yesterday"].append(n)
        elif days < 7:
            groups["this_week"].append(n)
        else:
            groups["older"].append(n)

    period_labels = [
        ("today", "Aujourd'hui"),
        ("yesterday", "Hier"),
        ("this_week", "Cette semaine"),
        ("older", "Plus ancien"),
    ]

    result = []
    for key, label in period_labels:
        if groups[key]:
            result.append({
                "key": key,
                "label": label,
                "notif_list": groups[key]
            })

    return result


# ─── HTML Page Route ──────────────────────────────────────────────────────────

@router.get("/notifications", response_class=HTMLResponse)
async def notifications_view(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Renders the Notifications timeline view.
    Executes auto-read cleanup for expired items upon loading.
    """
    # 1. Get current user if authenticated session exists
    current_user = None
    if request.session.get("authenticated") is True:
        username = request.session.get("username")
        if username:
            current_user = db.query(models.User).filter(models.User.username == username).first()

    # 2. Run auto-read policy & refresh standard user task notifications
    try:
        auto_mark_read_expired_notifications(db)
        refresh_standard_user_tasks_notifications(db)
    except Exception as exc:
        print(f"[Notifications] Error during auto-mark-read/refresh: {exc}")

    # 3. Retrieve notifications visible to the user
    query = get_user_notifications_query(db, current_user)
    notifications = query.all()

    unread_cnt = sum(1 for n in notifications if not n.is_read)
    read_cnt = sum(1 for n in notifications if n.is_read)
    annonce_cnt = sum(1 for n in notifications if n.category == "annonce")
    visite_cnt = sum(1 for n in notifications if n.category == "visite")
    systeme_cnt = sum(1 for n in notifications if n.category not in ("annonce", "visite"))

    grouped_periods = _group_notifications_by_period(notifications)

    from app.translations import get_text

    return templates.TemplateResponse(
        request=request,
        name="notifications.html",
        context={
            "user": current_user,
            "notifications": notifications,
            "grouped_periods": grouped_periods,
            "unread_cnt": unread_cnt,
            "read_cnt": read_cnt,
            "total_cnt": len(notifications),
            "annonce_cnt": annonce_cnt,
            "visite_cnt": visite_cnt,
            "systeme_cnt": systeme_cnt,
            "title": f"{get_text(request, 'nav.notifications', 'Notifications')} — {get_text(request, 'app.title')}",
        }
    )


# ─── REST API Endpoints ───────────────────────────────────────────────────────

@router.get("/api/v1/notifications/unread-count")
@router.get("/api/notifications/unread-count")
async def get_unread_count(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Returns unread notifications count for sidebar badge update.
    """
    current_user = None
    if request.session.get("authenticated") is True:
        username = request.session.get("username")
        if username:
            current_user = db.query(models.User).filter(models.User.username == username).first()

    try:
        refresh_standard_user_tasks_notifications(db)
    except Exception:
        pass

    count = get_unread_notifications_count(db, current_user)
    return JSONResponse({"unread_count": count})


@router.post("/api/v1/notifications/mark-read")
@router.post("/api/notifications/mark-read")
async def mark_notifications_read(
    payload: MarkReadRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Marks specified notification IDs as read.
    """
    if not payload.notification_ids:
        return JSONResponse({"status": "ok", "updated_count": 0})

    now = datetime.now(timezone.utc)
    updated = db.query(models.Notification).filter(
        models.Notification.id.in_(payload.notification_ids),
        models.Notification.is_read == False
    ).update(
        {models.Notification.is_read: True, models.Notification.read_at: now},
        synchronize_session=False
    )
    db.commit()
    return JSONResponse({"status": "ok", "updated_count": updated})


@router.post("/api/v1/notifications/mark-all-read")
@router.post("/api/notifications/mark-all-read")
async def mark_all_notifications_read(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Marks all notifications for current user/role/profile as read.
    """
    current_user = None
    if request.session.get("authenticated") is True:
        username = request.session.get("username")
        if username:
            current_user = db.query(models.User).filter(models.User.username == username).first()

    now = datetime.now(timezone.utc)
    query = get_user_notifications_query(db, current_user).filter(models.Notification.is_read == False)
    updated = query.update(
        {models.Notification.is_read: True, models.Notification.read_at: now},
        synchronize_session=False
    )
    db.commit()
    return JSONResponse({"status": "ok", "updated_count": updated})


@router.post("/api/v1/notifications/delete")
@router.post("/api/notifications/delete")
async def delete_notifications(
    payload: DeleteNotificationsRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Deletes specified notification IDs.
    """
    if not payload.notification_ids:
        return JSONResponse({"status": "ok", "deleted_count": 0})

    deleted = db.query(models.Notification).filter(
        models.Notification.id.in_(payload.notification_ids)
    ).delete(synchronize_session=False)
    db.commit()
    return JSONResponse({"status": "ok", "deleted_count": deleted})


@router.post("/api/v1/notifications/purge-all")
@router.post("/api/notifications/purge-all")
async def purge_all_notifications(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Purges all notifications for current user.
    """
    current_user = None
    if request.session.get("authenticated") is True:
        username = request.session.get("username")
        if username:
            current_user = db.query(models.User).filter(models.User.username == username).first()

    query = get_user_notifications_query(db, current_user)
    deleted = query.delete(synchronize_session=False)
    db.commit()
    return JSONResponse({"status": "ok", "deleted_count": deleted})
