"""
Notification module for Immo-Boussole.

Uses the Apprise library to send push notifications to users when new listings
are discovered during a scraping cycle. Supports any Apprise-compatible URL
(Telegram, Discord, ntfy, Pushover, email, Gotify, etc.).
"""
import asyncio
import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings

logger = logging.getLogger(__name__)


# ─── Internal Helper ──────────────────────────────────────────────────────────

def _send_via_apprise(apprise_url: str, title: str, body: str) -> bool:
    """
    Sends a notification synchronously via Apprise to a single URL.

    Returns True on success, False on failure.
    """
    try:
        import apprise  # lazy import — only required at runtime
    except ImportError:
        logger.warning(
            "[Notifications] apprise is not installed. "
            "Run: pip install apprise"
        )
        return False

    ap = apprise.Apprise()
    ap.add(apprise_url)

    result = ap.notify(title=title, body=body)
    if not result:
        logger.warning("[Notifications] Apprise notify() returned False for URL: %s", apprise_url[:30])
    return result


# ─── Public API ───────────────────────────────────────────────────────────────

async def send_new_listing_notifications(new_listings: list, db: Session) -> None:
    """
    Sends push notifications to all users after a scraping cycle.

    For each user:
      - Uses their personal ``apprise_url`` if configured.
      - Falls back to the global ``APPRISE_URL`` env variable.
      - Does nothing if neither is set.

    Listings that are marked as duplicates (``is_duplicate=True``) are excluded
    from the notification body to avoid noise.

    Args:
        new_listings: List of ``Listing`` ORM objects that are newly discovered.
        db: Active SQLAlchemy session (used to query users).
    """
    from app.models import User  # avoid circular import at module level

    if not new_listings:
        return

    # Filter out duplicates for the notification body
    genuine_new = [l for l in new_listings if not l.is_duplicate]
    if not genuine_new:
        return

    count = len(genuine_new)

    # Build notification content
    title = f"🏡 {count} nouvelle{'s' if count > 1 else ''} annonce{'s' if count > 1 else ''} — Immo-Boussole"
    lines = []
    for listing in genuine_new[:10]:  # cap at 10 items to avoid truncation
        price_str = f"{int(listing.price):,}€".replace(",", " ") if listing.price else "Prix N/C"
        area_str = f" · {int(listing.area)}m²" if listing.area else ""
        city_str = f" · {listing.city}" if listing.city else ""
        lines.append(f"• {listing.title or 'Annonce'}{city_str}{area_str} — {price_str}")

    if count > 10:
        lines.append(f"… et {count - 10} autre(s)")

    body = "\n".join(lines)

    # Also create in-app notification in DB
    try:
        first_listing_url = f"/listings/table?id={genuine_new[0].id}" if genuine_new else "/listings/table"
        create_in_app_notification(
            db=db,
            title=title,
            message=body,
            category="annonce",
            link_url=first_listing_url,
        )
    except Exception as exc:
        logger.warning(f"[Notifications] Error saving in-app notification: {exc}")

    # Collect unique Apprise URLs to notify
    # Key: apprise_url → list of usernames (for logging)
    urls_to_notify: dict[str, list[str]] = {}

    users = db.query(User).all()
    for user in users:
        url = user.apprise_url or settings.APPRISE_URL or ""
        url = url.strip()
        if url:
            urls_to_notify.setdefault(url, []).append(user.username)

    if not urls_to_notify:
        logger.debug("[Notifications] No Apprise URLs configured — skipping external notification.")
        return

    # Send notifications in background threads (Apprise is synchronous)
    loop = asyncio.get_event_loop()
    for url, usernames in urls_to_notify.items():
        logger.info(
            "[Notifications] Sending notification to %s (users: %s)",
            url[:30] + "…",
            ", ".join(usernames),
        )
        await loop.run_in_executor(None, _send_via_apprise, url, title, body)


async def send_test_notification(apprise_url: str) -> bool:
    """
    Sends a test notification to a single Apprise URL.
    Used by the ``POST /api/notifications/test`` endpoint.

    Returns True on success, False on failure.
    """
    title = "✅ Test Immo-Boussole"
    body = (
        "Vos notifications sont correctement configurées !\n"
        "Vous recevrez une alerte à chaque nouvelle annonce détectée."
    )
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _send_via_apprise, apprise_url, title, body)


# ─── In-App Notifications API ──────────────────────────────────────────────────

def create_in_app_notification(
    db: Session,
    title: str,
    message: str,
    category: str = "systeme",
    user_id: Optional[int] = None,
    target_role: Optional[str] = None,
    target_profile_id: Optional[int] = None,
    link_url: Optional[str] = None,
):
    """Creates and persists an in-app notification in SQLite."""
    from app.models import Notification
    notif = Notification(
        user_id=user_id,
        target_role=target_role,
        target_profile_id=target_profile_id,
        title=title,
        message=message,
        category=category,
        link_url=link_url,
        is_read=False,
    )
    db.add(notif)
    db.commit()
    db.refresh(notif)
    return notif


def get_user_notifications_query(db: Session, user: Optional[object] = None):
    """
    Returns a SQLAlchemy Query for notifications visible to the given user.
    """
    from app.models import Notification
    from sqlalchemy import or_

    query = db.query(Notification)
    if user is not None and getattr(user, "id", None) is not None:
        user_id = getattr(user, "id")
        user_role = getattr(user, "role", "user")
        query = query.filter(
            or_(Notification.user_id == user_id, Notification.user_id.is_(None)),
            or_(Notification.target_role.is_(None), Notification.target_role == user_role)
        )
    return query.order_by(Notification.created_at.desc())


def get_unread_notifications_count(db: Session, user: Optional[object] = None) -> int:
    """
    Counts unread notifications visible to the user.
    """
    from app.models import Notification
    query = get_user_notifications_query(db, user)
    return query.filter(Notification.is_read == False).count()


def auto_mark_read_expired_notifications(db: Session) -> int:
    """
    Performs auto-read cleanup based on each user's ``auto_read_after_days`` preference.
    """
    from datetime import datetime, timedelta, timezone
    from app.models import Notification, User
    from sqlalchemy import or_

    now = datetime.now(timezone.utc)
    users = db.query(User).all()
    total_updated = 0

    if not users:
        # Default fallback threshold of 30 days
        cutoff = now - timedelta(days=30)
        updated = db.query(Notification).filter(
            Notification.is_read == False,
            Notification.created_at <= cutoff
        ).update(
            {Notification.is_read: True, Notification.read_at: now},
            synchronize_session=False
        )
        db.commit()
        return updated

    for user in users:
        days = getattr(user, "auto_read_after_days", 30) or 30
        cutoff = now - timedelta(days=days)
        unread_q = db.query(Notification).filter(
            Notification.is_read == False,
            Notification.created_at <= cutoff,
            or_(Notification.user_id == user.id, Notification.user_id.is_(None)),
            or_(Notification.target_role.is_(None), Notification.target_role == user.role)
        )
        count = unread_q.update(
            {Notification.is_read: True, Notification.read_at: now},
            synchronize_session=False
        )
        total_updated += count

    db.commit()
    return total_updated
