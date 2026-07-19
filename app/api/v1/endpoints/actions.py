from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.api.deps import get_current_user_api
from app.services import scrape_and_diff

router = APIRouter()

@router.post("/submit-url", response_model=schemas.ActionResponse)
async def submit_url_api(
    request: schemas.SubmitUrlRequest,
    background_tasks: BackgroundTasks,
    current_user: models.User = Depends(get_current_user_api),
    db: Session = Depends(get_db)
):
    """
    Trigger scraping for a given URL.
    Returns immediately, task runs in background.
    """
    if request.skip_scraping:
        from app.services import create_listing_from_details
        create_listing_from_details(request.url, db)
        return schemas.ActionResponse(status="success", message="Listing added manually without scraping.")
    
    background_tasks.add_task(scrape_and_diff, request.url, db)
    return schemas.ActionResponse(status="accepted", message="Scraping task started in background.")
