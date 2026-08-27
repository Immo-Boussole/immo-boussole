from fastapi import APIRouter

from app.api.v1.endpoints import users, listings, actions, contacts, auth, notifications

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
api_router.include_router(users.router, prefix="/users", tags=["Users / API Keys"])
api_router.include_router(listings.router, prefix="/listings", tags=["Listings"])
api_router.include_router(actions.router, prefix="/actions", tags=["Actions & Tasks"])
api_router.include_router(contacts.router, tags=["Contacts & Google Auth"])
api_router.include_router(notifications.router, tags=["Notifications"])

