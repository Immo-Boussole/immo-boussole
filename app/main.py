from fastapi import FastAPI, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
import os

from app import models, database
from app.database import engine, get_db

# Créer les tables de la base de données
models.Base.metadata.create_all(bind=engine)

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    from app.scheduler import start_scheduler
    scheduler = start_scheduler()
    yield
    # Shutdown
    if scheduler.running:
        scheduler.shutdown()

app = FastAPI(title="Immo-Boussole", lifespan=lifespan)

# Création du dossier templates s'il n'existe pas
os.makedirs("templates", exist_ok=True)
templates = Jinja2Templates(directory="templates")

@app.get("/")
def read_root(request: Request, db: Session = Depends(get_db)):
    listings = db.query(models.Listing).order_by(models.Listing.date_added.desc()).limit(50).all()
    queries = db.query(models.SearchQuery).all()
    
    return templates.TemplateResponse("index.html", {
        "request": request, 
        "listings": listings,
        "queries": queries,
        "title": "Tableau de Bord - Immo-Boussole"
    })

@app.get("/api/listings")
def get_listings(db: Session = Depends(get_db), status: str = None):
    query = db.query(models.Listing)
    if status:
        query = query.filter(models.Listing.status == status)
    return query.order_by(models.Listing.date_added.desc()).limit(100).all()

# TODO: Add API routes for creating SearchQuery
