from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app import models, schemas
from app.database import get_db
from app.api.deps import get_current_user_api

router = APIRouter()

@router.get("/", response_model=List[schemas.ListingResponse])
def get_listings(
    skip: int = 0,
    limit: int = 100,
    current_user: models.User = Depends(get_current_user_api),
    db: Session = Depends(get_db)
):
    """
    Get listings.
    """
    listings = db.query(models.Listing).order_by(models.Listing.date_added.desc()).offset(skip).limit(limit).all()
    return listings

@router.get("/{listing_id}", response_model=schemas.ListingResponse)
def get_listing(
    listing_id: int,
    current_user: models.User = Depends(get_current_user_api),
    db: Session = Depends(get_db)
):
    listing = db.query(models.Listing).filter(models.Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    return listing


@router.get("/{listing_id}/attachments", response_model=List[schemas.ListingAttachmentResponse])
def get_listing_attachments_v1(
    listing_id: int,
    current_user: models.User = Depends(get_current_user_api),
    db: Session = Depends(get_db)
):
    listing = db.query(models.Listing).filter(models.Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    return db.query(models.ListingAttachment).filter(
        models.ListingAttachment.listing_id == listing_id
    ).order_by(models.ListingAttachment.created_at.desc()).all()


@router.get("/{listing_id}/links", response_model=List[schemas.ListingLinkResponse])
def get_listing_links_v1(
    listing_id: int,
    current_user: models.User = Depends(get_current_user_api),
    db: Session = Depends(get_db)
):
    listing = db.query(models.Listing).filter(models.Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    return db.query(models.ListingLink).filter(
        models.ListingLink.listing_id == listing_id
    ).order_by(models.ListingLink.created_at.asc()).all()


@router.post("/{listing_id}/set-location")
def set_listing_location_v1(
    listing_id: int,
    payload: dict,
    current_user: models.User = Depends(get_current_user_api),
    db: Session = Depends(get_db)
):
    """Update listing location via API v1."""
    location = (payload.get("location") or "").strip()
    if not location:
        raise HTTPException(status_code=400, detail="Location is required")

    listing = db.query(models.Listing).filter(models.Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    from app.geo import standardize_and_enrich_city, get_coordinates
    from app.main import _is_city_in_allowed_departments
    from app.models import ZoneRule, ListingStatus
    from app.geo import is_city_in_forbidden_set

    std_city, std_postal_code, _ = standardize_and_enrich_city(location)
    final_city = std_city or location

    listing.city = final_city
    listing.location = final_city
    if payload.get("postal_code"):
        listing.postal_code = payload["postal_code"].strip()
    elif std_postal_code:
        listing.postal_code = std_postal_code

    listing.address_precision = "city"
    listing.manual_address_override = True

    if payload.get("latitude") is not None and payload.get("longitude") is not None:
        listing.latitude = float(payload["latitude"])
        listing.longitude = float(payload["longitude"])
    else:
        coords = get_coordinates(final_city)
        if coords:
            listing.latitude, listing.longitude = coords

    was_rejected = False
    if not listing.to_visit:
        if not _is_city_in_allowed_departments(final_city, db):
            listing.status = ListingStatus.REJECTED
            was_rejected = True
        else:
            forbidden_cities = {r.name.strip().lower() for r in db.query(ZoneRule).filter(
                ZoneRule.zone_type == "city", ZoneRule.rule == "forbidden"
            ).all()}
            if is_city_in_forbidden_set(final_city, forbidden_cities):
                listing.status = ListingStatus.REJECTED
                was_rejected = True

    listing.update_price_per_sqm()
    db.commit()
    db.refresh(listing)

    return {
        "success": True,
        "listing_id": listing.id,
        "city": listing.city,
        "location": listing.location,
        "postal_code": listing.postal_code,
        "latitude": listing.latitude,
        "longitude": listing.longitude,
        "status": listing.status.value if hasattr(listing.status, 'value') else str(listing.status),
        "is_rejected": was_rejected,
        "listing": {
            "id": listing.id,
            "title": listing.title,
            "city": listing.city,
            "location": listing.location,
            "postal_code": listing.postal_code,
            "latitude": listing.latitude,
            "longitude": listing.longitude,
            "status": listing.status.value if hasattr(listing.status, 'value') else str(listing.status),
            "is_rejected": was_rejected
        }
    }


def _render_native_fallback_preview(listing: models.Listing, reason: str = "") -> str:
    """Generate a clean native fallback HTML preview when source portal restricts direct framing."""
    import json
    import html

    photos = []
    if listing.photos_local:
        try:
            p_list = json.loads(listing.photos_local)
            if isinstance(p_list, list):
                photos.extend([p for p in p_list if p])
        except Exception:
            pass
    if not photos and listing.original_photo_urls:
        try:
            p_list = json.loads(listing.original_photo_urls)
            if isinstance(p_list, list):
                photos.extend([p for p in p_list if p])
        except Exception:
            pass

    price_str = f"{int(listing.price):,} €".replace(",", " ") if listing.price else "Prix non renseigné"
    area_str = f"{listing.area} m²" if listing.area else ""
    source_name = listing.source.value if hasattr(listing.source, 'value') else str(listing.source or "Source")
    target_url = listing.original_url or listing.url or "#"

    photos_html = ""
    if photos:
        thumb_items = "".join(
            '<img src="{src}" class="thumb-item {cls}" onclick="selectThumb(this, \'{src}\')" alt="Thumb">'.format(
                src=html.escape(p),
                cls="active" if i == 0 else ""
            )
            for i, p in enumerate(photos[:12])
        )
        photos_html = f"""
        <div class="gallery">
            <div class="main-photo-wrap">
                <img id="mainPreviewImg" src="{html.escape(photos[0])}" class="main-photo" alt="Photo">
            </div>
            <div class="thumbnails">
                {thumb_items}
            </div>
        </div>
        """
    else:
        photos_html = """
        <div class="no-photo">
            <i class="fa-regular fa-image" style="font-size:3rem;opacity:0.4;"></i>
            <p>Aucune photo disponible</p>
        </div>
        """

    desc_escaped = html.escape(listing.description_text or "Aucune description détaillée enregistrée.").replace("\n", "<br>")

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Aperçu : {html.escape(listing.title or 'Annonce')}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root {{
            --bg: #0f172a;
            --surface: #1e293b;
            --surface-2: #334155;
            --text: #f8fafc;
            --text-2: #94a3b8;
            --accent: #4f8ef7;
            --border: rgba(255,255,255,0.08);
            --radius: 12px;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: var(--bg);
            color: var(--text);
            padding: 1.5rem;
            line-height: 1.6;
        }}
        .notice-banner {{
            background: rgba(79, 142, 247, 0.12);
            border: 1px solid rgba(79, 142, 247, 0.3);
            border-radius: 8px;
            padding: 0.85rem 1rem;
            margin-bottom: 1.25rem;
            font-size: 0.85rem;
            color: #93c5fd;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            flex-wrap: wrap;
        }}
        .btn-ext {{
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            background: var(--accent);
            color: white;
            padding: 0.45rem 0.85rem;
            border-radius: 6px;
            text-decoration: none;
            font-weight: 600;
            font-size: 0.82rem;
            transition: opacity 0.2s;
        }}
        .btn-ext:hover {{ opacity: 0.9; }}
        .header {{
            margin-bottom: 1.25rem;
        }}
        .badge-source {{
            display: inline-block;
            background: rgba(255,255,255,0.1);
            padding: 0.2rem 0.5rem;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--accent);
            margin-bottom: 0.4rem;
        }}
        .title {{
            font-size: 1.35rem;
            font-weight: 700;
            margin-bottom: 0.5rem;
            line-height: 1.3;
        }}
        .meta-pills {{
            display: flex;
            align-items: center;
            gap: 0.75rem;
            font-size: 1.1rem;
            font-weight: 600;
            color: var(--accent);
            margin-bottom: 1rem;
        }}
        .gallery {{
            margin-bottom: 1.5rem;
        }}
        .main-photo-wrap {{
            width: 100%;
            height: 380px;
            border-radius: var(--radius);
            overflow: hidden;
            background: var(--surface);
            margin-bottom: 0.6rem;
            border: 1px solid var(--border);
        }}
        .main-photo {{
            width: 100%;
            height: 100%;
            object-fit: cover;
            transition: opacity 0.2s;
        }}
        .thumbnails {{
            display: flex;
            gap: 0.5rem;
            overflow-x: auto;
            padding-bottom: 0.4rem;
        }}
        .thumb-item {{
            width: 68px;
            height: 52px;
            border-radius: 6px;
            object-fit: cover;
            cursor: pointer;
            border: 2px solid transparent;
            opacity: 0.6;
            transition: all 0.2s;
            flex-shrink: 0;
        }}
        .thumb-item.active, .thumb-item:hover {{
            opacity: 1;
            border-color: var(--accent);
        }}
        .no-photo {{
            background: var(--surface);
            border: 1px dashed var(--border);
            border-radius: var(--radius);
            padding: 3rem;
            text-align: center;
            color: var(--text-2);
            margin-bottom: 1.5rem;
        }}
        .desc-card {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 1.25rem;
            font-size: 0.92rem;
            line-height: 1.7;
            color: #cbd5e1;
            word-break: break-word;
        }}
        .desc-title {{
            font-size: 1rem;
            font-weight: 700;
            color: var(--text);
            margin-bottom: 0.75rem;
        }}
    </style>
</head>
<body>
    <div class="notice-banner">
        <span><i class="fa-solid fa-circle-info"></i> Affichage extrait de l'annonce d'origine ({html.escape(source_name)}).</span>
        <a href="{html.escape(target_url)}" target="_blank" class="btn-ext">
            Ouvrir la page source originale <i class="fa-solid fa-arrow-up-right-from-square"></i>
        </a>
    </div>

    <div class="header">
        <span class="badge-source">{html.escape(source_name)}</span>
        <h1 class="title">{html.escape(listing.title or 'Sans titre')}</h1>
        <div class="meta-pills">
            <span>{price_str}</span>
            {f'<span>• {html.escape(area_str)}</span>' if area_str else ''}
            {f'<span>• {listing.rooms} pièces</span>' if listing.rooms else ''}
        </div>
    </div>

    {photos_html}

    <div class="desc-card">
        <div class="desc-title">Description de l'annonce</div>
        <div>{desc_escaped}</div>
    </div>

    <script>
        function selectThumb(el, src) {{
            document.querySelectorAll('.thumb-item').forEach(t => t.classList.remove('active'));
            el.classList.add('active');
            const main = document.getElementById('mainPreviewImg');
            if (main) main.src = src;
        }}
    </script>
</body>
</html>"""


@router.get("/{listing_id}/source-preview-html")
def get_listing_source_preview_html(
    listing_id: int,
    current_user: models.User = Depends(get_current_user_api),
    db: Session = Depends(get_db)
):
    """
    Fetch and sanitize source portal HTML for the right side drawer preview.
    Strips X-Frame-Options and CSP frame-ancestors, injects <base href> and anti-frame-busting guard.
    Falls back gracefully to rich native preview if portal restricts direct access.
    """
    from fastapi.responses import HTMLResponse
    import httpx
    import re

    listing = db.query(models.Listing).filter(models.Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    target_url = listing.original_url or listing.url
    if not target_url or not target_url.startswith("http"):
        return HTMLResponse(content=_render_native_fallback_preview(listing, "URL non disponible"), status_code=200)

    # Attempt to fetch live HTML
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.google.com/"
        }
        with httpx.Client(timeout=8.0, follow_redirects=True) as client:
            resp = client.get(target_url, headers=headers)
            if resp.status_code == 200 and "text/html" in resp.headers.get("content-type", ""):
                raw_html = resp.text
                # Clean frame busting / CSP meta
                clean_html = re.sub(r'<meta[^>]*http-equiv=["\']?Content-Security-Policy["\']?[^>]*>', '', raw_html, flags=re.IGNORECASE)
                clean_html = re.sub(r'<meta[^>]*http-equiv=["\']?X-Frame-Options["\']?[^>]*>', '', clean_html, flags=re.IGNORECASE)
                
                # Injects anti-framebusting override & base href
                injection = f"""
                <base href="{target_url}">
                <script>
                    try {{
                        Object.defineProperty(window, 'top', {{ get: function() {{ return window.self; }} }});
                        Object.defineProperty(window, 'parent', {{ get: function() {{ return window.self; }} }});
                    }} catch(e) {{}}
                </script>
                """
                if "<head>" in clean_html:
                    clean_html = clean_html.replace("<head>", f"<head>{injection}", 1)
                elif "<HEAD>" in clean_html:
                    clean_html = clean_html.replace("<HEAD>", f"<HEAD>{injection}", 1)
                else:
                    clean_html = injection + clean_html

                return HTMLResponse(
                    content=clean_html,
                    status_code=200,
                    headers={
                        "X-Frame-Options": "SAMEORIGIN",
                        "Content-Security-Policy": "frame-ancestors 'self'"
                    }
                )
    except Exception:
        pass

    # Fallback to Tier 3 Rich Native Preview
    return HTMLResponse(
        content=_render_native_fallback_preview(listing),
        status_code=200,
        headers={
            "X-Frame-Options": "SAMEORIGIN",
            "Content-Security-Policy": "frame-ancestors 'self'"
        }
    )


