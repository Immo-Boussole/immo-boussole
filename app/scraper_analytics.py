"""
Scraper Analytics Engine: Statistical analysis and defect identification for scrapers and parsers.
"""
from datetime import datetime, timedelta, timezone
import json
import math
import re
import time
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models import Listing, ListingStatus, Source
from app.services import is_error_or_generic_title, has_valid_local_photos, is_missing_or_corrupt_photos


# Scraper portal display metadata
SCRAPER_METADATA: Dict[str, Dict[str, str]] = {
    "leboncoin": {
        "name": "Leboncoin",
        "icon": "fa-solid fa-tag",
        "color": "#ea580c",
        "domain": "leboncoin.fr",
    },
    "seloger": {
        "name": "SeLoger",
        "icon": "fa-solid fa-house-chimney",
        "color": "#e11d48",
        "domain": "seloger.com",
    },
    "lefigaro": {
        "name": "Le Figaro Immobilier",
        "icon": "fa-solid fa-newspaper",
        "color": "#2563eb",
        "domain": "immobilier.lefigaro.fr",
    },
    "logicimmo": {
        "name": "Logic-Immo",
        "icon": "fa-solid fa-building",
        "color": "#0d9488",
        "domain": "logic-immo.com",
    },
    "bienici": {
        "name": "Bien'Ici",
        "icon": "fa-solid fa-location-dot",
        "color": "#ca8a04",
        "domain": "bienici.com",
    },
    "iadfrance": {
        "name": "IAD France",
        "icon": "fa-solid fa-network-wired",
        "color": "#7c3aed",
        "domain": "iadfrance.fr",
    },
    "orpi": {
        "name": "Orpi",
        "icon": "fa-solid fa-circle-dot",
        "color": "#dc2626",
        "domain": "orpi.com",
    },
    "provimo": {
        "name": "Provimo",
        "icon": "fa-solid fa-compass",
        "color": "#059669",
        "domain": "provimo.fr",
    },
    "hektor": {
        "name": "Hektor / Apimo",
        "icon": "fa-solid fa-server",
        "color": "#4f46e5",
        "domain": "hektor.immo",
    },
    "notaires": {
        "name": "Immobilier Notaires",
        "icon": "fa-solid fa-scale-balanced",
        "color": "#475569",
        "domain": "immobilier.notaires.fr",
    },
    "vinci": {
        "name": "Vinci Immobilier",
        "icon": "fa-solid fa-cubes",
        "color": "#0284c7",
        "domain": "vinci-immobilier.com",
    },
    "immobilier_france": {
        "name": "Immobilier France",
        "icon": "fa-solid fa-map",
        "color": "#16a34a",
        "domain": "immobilier-france.fr",
    },
    "manuel": {
        "name": "Saisie Manuelle",
        "icon": "fa-solid fa-hand",
        "color": "#64748b",
        "domain": "manuel",
    },
}

# Cache settings
_CACHE: Dict[str, Any] = {"data": None, "timestamp": 0.0}
CACHE_TTL_SECONDS = 600.0  # 10 minutes


def clear_scraper_analytics_cache() -> None:
    """Clears the in-memory analytics cache."""
    global _CACHE
    _CACHE = {"data": None, "timestamp": 0.0}


def _calculate_percentiles(values: List[float]) -> Dict[str, Optional[float]]:
    """Calculates min, max, mean, median, Q1 (25th), Q3 (75th), and IQR from a list of floats."""
    if not values:
        return {
            "min": None,
            "max": None,
            "mean": None,
            "median": None,
            "q25": None,
            "q75": None,
            "iqr": None,
        }
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    val_min = round(sorted_vals[0], 2)
    val_max = round(sorted_vals[-1], 2)
    val_mean = round(sum(sorted_vals) / n, 2)

    def _percentile(p: float) -> float:
        k = (n - 1) * p
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_vals[int(k)]
        return sorted_vals[int(f)] * (c - k) + sorted_vals[int(c)] * (k - f)

    q25 = round(_percentile(0.25), 2)
    median = round(_percentile(0.50), 2)
    q75 = round(_percentile(0.75), 2)
    iqr = round(max(0.0, q75 - q25), 2)

    return {
        "min": val_min,
        "max": val_max,
        "mean": val_mean,
        "median": median,
        "q25": q25,
        "q75": q75,
        "iqr": iqr,
    }


def _has_html_residue(text: Optional[str]) -> bool:
    """Checks if text contains raw HTML tags, unescaped entities or JSON string fragments."""
    if not text:
        return False
    t = text.strip()
    if re.search(r'<\/?(?:p|div|br|span|b|strong|ul|li|a|h\d|table|tr|td)[\s>\/]', t, re.IGNORECASE):
        return True
    if re.search(r'&(?:nbsp|amp|quot|lt|gt|#\d+);', t, re.IGNORECASE):
        return True
    if t.startswith("{") and t.endswith("}") and '"' in t:
        return True
    return False


def _has_duplicate_zip(location: Optional[str]) -> bool:
    """Checks if location has duplicated postal code e.g. 'Chavanay (42) (42)'."""
    if not location:
        return False
    return bool(re.search(r'\s*\((\d{2,5})\)\s*\(\1\)$', location.strip()))


def _is_valid_dpe(energy: Optional[str]) -> bool:
    """Checks whether energy class is a valid French DPE grade (A-G)."""
    if not energy:
        return False
    e = energy.strip().upper()
    return e in ("A", "B", "C", "D", "E", "F", "G")


def _is_city_standardized(city: Optional[str]) -> bool:
    """Checks if city matches 'Nom (CodePostal)' format."""
    if not city:
        return False
    return bool(re.match(r'^.+\s\(\d{5}\)$', city.strip()))


def _listing_summary(l: Listing, anomaly_reason: str, anomaly_value: Any = None) -> Dict[str, Any]:
    """Generates a compact listing dictionary for drill-down inspection."""
    return {
        "id": l.id,
        "title": l.title or "Sans titre",
        "city": l.city or l.location or "Non précisée",
        "price": l.price,
        "area": l.area,
        "price_per_sqm": l.price_per_sqm,
        "url": l.url or f"/listing/{l.id}",
        "external_id": l.external_id,
        "date_added": l.date_added.isoformat() if l.date_added else None,
        "anomaly_reason": anomaly_reason,
        "anomaly_value": anomaly_value,
    }


def compute_scraper_analytics(db: Session) -> Dict[str, Any]:
    """
    Analyzes the health, completeness, statistical distributions, anomalies,
    and temporal ingestion drifts of all scrapers/parsers.
    """
    now = datetime.now(timezone.utc)
    seven_days_ago = now - timedelta(days=7)
    thirty_seven_days_ago = now - timedelta(days=37)

    all_listings: List[Listing] = db.query(Listing).all()

    # Group listings by source
    listings_by_source: Dict[str, List[Listing]] = {}
    for l in all_listings:
        src = str(l.source.value if hasattr(l.source, "value") else (l.source or "manuel")).lower()
        listings_by_source.setdefault(src, []).append(l)

    # Ensure all known metadata sources are present in results even if 0 listings
    for known_src in SCRAPER_METADATA.keys():
        if known_src not in listings_by_source:
            listings_by_source[known_src] = []

    scrapers_result: Dict[str, Any] = {}
    global_total_listings = len(all_listings)
    global_active_listings = 0
    all_global_anomalies_count = 0

    for source_key, source_listings in listings_by_source.items():
        total_count = len(source_listings)
        active_listings = [
            l for l in source_listings
            if str(l.status.value if hasattr(l.status, "value") else (l.status or "")).lower() in ("active", "nouvelle")
        ]
        active_count = len(active_listings)
        global_active_listings += active_count

        # Target set for completeness and outlier detection:
        # Prefer active listings, fallback to all source listings if none active
        target_listings = active_listings if active_count > 0 else source_listings
        target_count = len(target_listings)

        # 1. Temporal flux / Volumetry
        recent_7d = [
            l for l in source_listings
            if l.date_added and (
                (l.date_added if l.date_added.tzinfo else l.date_added.replace(tzinfo=timezone.utc)) >= seven_days_ago
            )
        ]
        prev_30d = [
            l for l in source_listings
            if l.date_added and (
                seven_days_ago > (l.date_added if l.date_added.tzinfo else l.date_added.replace(tzinfo=timezone.utc)) >= thirty_seven_days_ago
            )
        ]
        recent_7d_count = len(recent_7d)
        prev_30d_daily_avg = round(len(prev_30d) / 30.0, 2)
        current_7d_daily_avg = round(recent_7d_count / 7.0, 2)

        volume_trend_pct = 0.0
        flux_drop_warning = False
        if prev_30d_daily_avg > 0.1:
            volume_trend_pct = round(((current_7d_daily_avg - prev_30d_daily_avg) / prev_30d_daily_avg) * 100.0, 1)
            # If drop is > 60% compared to previous 30d baseline on an established scraper
            if volume_trend_pct <= -60.0 and len(source_listings) >= 10:
                flux_drop_warning = True

        # 2. Completeness analysis
        completeness_counts = {
            "price": 0,
            "area": 0,
            "price_per_sqm": 0,
            "energy_class": 0,
            "ges_class": 0,
            "rooms": 0,
            "bedrooms": 0,
            "description": 0,
            "photos": 0,
            "city_standardized": 0,
            "agency_fee": 0,
            "floor": 0,
        }

        # Anomaly tracking per category
        anomalies_lists: Dict[str, List[Dict[str, Any]]] = {
            "price_outliers": [],
            "area_outliers": [],
            "price_sqm_outliers": [],
            "generic_titles": [],
            "missing_photos": [],
            "missing_dpe": [],
            "html_residue": [],
            "empty_description": [],
            "unstandardized_city": [],
            "duplicate_city_zip": [],
        }

        prices: List[float] = []
        areas: List[float] = []
        prices_per_sqm: List[float] = []

        for l in target_listings:
            # Price
            if l.price is not None and l.price > 0:
                completeness_counts["price"] += 1
                prices.append(float(l.price))
                if l.price < 5000 or l.price > 10000000:
                    anomalies_lists["price_outliers"].append(
                        _listing_summary(l, "Prix anormal / aberrant", f"{int(l.price):,} €")
                    )
            else:
                anomalies_lists["price_outliers"].append(
                    _listing_summary(l, "Prix absent ou nul", l.price)
                )

            # Area
            if l.area is not None and l.area > 0:
                completeness_counts["area"] += 1
                areas.append(float(l.area))
                if l.area < 9 or l.area > 1500:
                    anomalies_lists["area_outliers"].append(
                        _listing_summary(l, "Surface hors normes", f"{l.area} m²")
                    )
            else:
                anomalies_lists["area_outliers"].append(
                    _listing_summary(l, "Surface absente ou nulle", l.area)
                )

            # Price per SQM
            if l.price_per_sqm is not None and l.price_per_sqm > 0:
                completeness_counts["price_per_sqm"] += 1
                prices_per_sqm.append(float(l.price_per_sqm))
            elif l.price and l.area and l.price > 0 and l.area > 0:
                calc_sqm = round(l.price / l.area, 2)
                prices_per_sqm.append(calc_sqm)

            # Energy rating & GES
            if _is_valid_dpe(l.dpe_rating):
                completeness_counts["energy_class"] += 1
            else:
                anomalies_lists["missing_dpe"].append(
                    _listing_summary(l, "DPE manquant ou NC", l.dpe_rating or "Non renseigné")
                )

            if _is_valid_dpe(l.ges_rating):
                completeness_counts["ges_class"] += 1

            # Rooms / Bedrooms
            if l.rooms is not None and l.rooms > 0:
                completeness_counts["rooms"] += 1
            if l.bedrooms is not None and l.bedrooms > 0:
                completeness_counts["bedrooms"] += 1

            # Photos
            if not is_missing_or_corrupt_photos(l):
                completeness_counts["photos"] += 1
            else:
                anomalies_lists["missing_photos"].append(
                    _listing_summary(l, "Photos absentes ou corrompues", "0 photo valide")
                )

            # Description
            desc = (l.description_text or "").strip()
            if len(desc) >= 30:
                completeness_counts["description"] += 1
            else:
                anomalies_lists["empty_description"].append(
                    _listing_summary(l, "Description vide ou trop courte", f"{len(desc)} caractères")
                )

            # Text quality: HTML residue
            if _has_html_residue(l.description_text):
                anomalies_lists["html_residue"].append(
                    _listing_summary(l, "Résidus de balises HTML ou encodage", "HTML détecté")
                )

            # Title quality
            if is_error_or_generic_title(l.title):
                anomalies_lists["generic_titles"].append(
                    _listing_summary(l, "Titre générique ou d'erreur", l.title)
                )

            # City standardization & Duplicate zip
            if _is_city_standardized(l.city):
                completeness_counts["city_standardized"] += 1
            else:
                anomalies_lists["unstandardized_city"].append(
                    _listing_summary(l, "Ville non standardisée", l.city or l.location or "Vide")
                )

            if _has_duplicate_zip(l.location):
                anomalies_lists["duplicate_city_zip"].append(
                    _listing_summary(l, "Code postal dupliqué dans localisation", l.location)
                )

            # Agency fee & Floor
            if l.agency_fee is not None or l.honoraires_a_charge is not None:
                completeness_counts["agency_fee"] += 1
            if l.floor is not None:
                completeness_counts["floor"] += 1

        # 3. Percentiles and IQR Outliers for Price / SQM
        price_dist = _calculate_percentiles(prices)
        area_dist = _calculate_percentiles(areas)
        price_sqm_dist = _calculate_percentiles(prices_per_sqm)

        # Flag IQR-based price/m² outliers
        if price_sqm_dist["iqr"] is not None and price_sqm_dist["q25"] is not None and price_sqm_dist["q75"] is not None:
            iqr = price_sqm_dist["iqr"]
            lower_bound = max(400.0, price_sqm_dist["q25"] - 2.5 * iqr)
            upper_bound = min(30000.0, price_sqm_dist["q75"] + 2.5 * iqr)

            for l in target_listings:
                val = l.price_per_sqm
                if not val and l.price and l.area and l.area > 0:
                    val = l.price / l.area
                if val:
                    if val < lower_bound or val > upper_bound:
                        anomalies_lists["price_sqm_outliers"].append(
                            _listing_summary(l, "Prix/m² hors distribution IQR", f"{int(val)} €/m² (normal: {int(lower_bound)}-{int(upper_bound)})")
                        )

        # 4. Completeness Rates (%)
        completeness_rates: Dict[str, float] = {}
        for field, count in completeness_counts.items():
            rate = round((count / target_count) * 100.0, 1) if target_count > 0 else 0.0
            completeness_rates[field] = rate

        # 5. Health Score Calculation (0-100)
        # Weights:
        # Essential fields (Price, Area, Photos, Description, City): 50%
        # Extended fields (DPE, Rooms, Price/sqm): 20%
        # Defect absence (generic titles, html residue, severe price/sqm outliers): 20%
        # Activity/Flux: 10%
        if target_count == 0:
            health_score = 100.0 if total_count == 0 else 50.0
        else:
            p_rate = completeness_rates["price"]
            a_rate = completeness_rates["area"]
            ph_rate = completeness_rates["photos"]
            d_rate = completeness_rates["description"]
            c_rate = completeness_rates["city_standardized"]
            dpe_rate = completeness_rates["energy_class"]
            r_rate = completeness_rates["rooms"]
            sqm_rate = completeness_rates["price_per_sqm"]

            essential_score = (p_rate * 0.25 + a_rate * 0.25 + ph_rate * 0.25 + d_rate * 0.15 + c_rate * 0.10)
            extended_score = (dpe_rate * 0.4 + r_rate * 0.3 + sqm_rate * 0.3)

            # Defect penalties
            generic_title_rate = (len(anomalies_lists["generic_titles"]) / target_count) * 100.0
            html_residue_rate = (len(anomalies_lists["html_residue"]) / target_count) * 100.0
            outlier_rate = (len(anomalies_lists["price_sqm_outliers"]) / target_count) * 100.0
            defect_score = max(0.0, 100.0 - (generic_title_rate * 1.5 + html_residue_rate * 1.5 + outlier_rate * 1.0))

            flux_score = 50.0 if flux_drop_warning else 100.0

            composite = (essential_score * 0.50) + (extended_score * 0.20) + (defect_score * 0.20) + (flux_score * 0.10)
            health_score = round(max(0.0, min(100.0, composite)), 1)

        # Status badge
        if target_count == 0 and total_count == 0:
            health_status = "idle"  # No listings scraped yet
        elif health_score >= 80.0 and not flux_drop_warning:
            health_status = "healthy"
        elif health_score >= 50.0 or flux_drop_warning:
            health_status = "degraded"
        else:
            health_status = "broken"

        total_anomalies_for_source = sum(len(items) for items in anomalies_lists.values())
        all_global_anomalies_count += total_anomalies_for_source

        meta = SCRAPER_METADATA.get(source_key, {
            "name": source_key.capitalize(),
            "icon": "fa-solid fa-globe",
            "color": "#6366f1",
            "domain": source_key,
        })

        scrapers_result[source_key] = {
            "source_key": source_key,
            "meta": meta,
            "counts": {
                "total": total_count,
                "active": active_count,
                "analyzed": target_count,
                "recent_7d": recent_7d_count,
                "prev_30d_daily_avg": prev_30d_daily_avg,
                "current_7d_daily_avg": current_7d_daily_avg,
                "volume_trend_pct": volume_trend_pct,
                "flux_drop_warning": flux_drop_warning,
            },
            "health": {
                "score": health_score,
                "status": health_status,
                "total_anomalies": total_anomalies_for_source,
            },
            "completeness_rates": completeness_rates,
            "completeness_counts": completeness_counts,
            "distributions": {
                "price": price_dist,
                "area": area_dist,
                "price_per_sqm": price_sqm_dist,
            },
            "anomalies": {
                k: {
                    "count": len(v),
                    "items": v[:50],  # Return up to 50 items for fast UI rendering
                }
                for k, v in anomalies_lists.items()
            },
        }

    # Summary KPIs
    active_scrapers = [s for s in scrapers_result.values() if s["counts"]["total"] > 0]
    avg_health_score = (
        round(sum(s["health"]["score"] for s in active_scrapers) / len(active_scrapers), 1)
        if active_scrapers
        else 100.0
    )

    healthy_count = sum(1 for s in active_scrapers if s["health"]["status"] == "healthy")
    degraded_count = sum(1 for s in active_scrapers if s["health"]["status"] == "degraded")
    broken_count = sum(1 for s in active_scrapers if s["health"]["status"] == "broken")
    idle_count = len(scrapers_result) - len(active_scrapers)

    return {
        "generated_at": now.isoformat(),
        "summary": {
            "total_listings": global_total_listings,
            "active_listings": global_active_listings,
            "total_scrapers": len(scrapers_result),
            "active_scrapers_count": len(active_scrapers),
            "healthy_count": healthy_count,
            "degraded_count": degraded_count,
            "broken_count": broken_count,
            "idle_count": idle_count,
            "avg_health_score": avg_health_score,
            "total_anomalies_count": all_global_anomalies_count,
        },
        "scrapers": scrapers_result,
    }


def get_scraper_analytics(db: Session, force_refresh: bool = False) -> Dict[str, Any]:
    """
    Returns scraper analytics with in-memory caching (TTL: 10 minutes).
    """
    global _CACHE
    now_ts = time.time()

    if not force_refresh and _CACHE["data"] is not None:
        if (now_ts - _CACHE["timestamp"]) < CACHE_TTL_SECONDS:
            return _CACHE["data"]

    data = compute_scraper_analytics(db)
    _CACHE["data"] = data
    _CACHE["timestamp"] = now_ts
    return data
