"""
Solar Potential and Sunshine Analysis Module for Immo-Boussole.
Integrates PVGIS (European Commission JRC API) and Open-Meteo with local caching,
orientation extraction, and PV rooftop production simulations (3 kWc / 6 kWc).
"""

import json
import logging
import math
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

# In-memory fast cache
_SOLAR_MEM_CACHE: Dict[str, Dict[str, Any]] = {}

# Electricity tariff constants for France (approx 2025/2026 residential baseline)
# Average grid electricity price (€/kWh TTC)
GRID_ELEC_PRICE_KWH = 0.2516
# Surplus feed-in tariff (tarif rachat surplus EDF OA €/kWh for <= 9 kWc)
SURPLUS_FEED_IN_PRICE_KWH = 0.1300
# Estimated self-consumption ratio for residential PV without battery
RESIDENTIAL_SELF_CONSUMPTION_RATIO = 0.40


def _get_geo_cache_key(lat: float, lon: float) -> str:
    """Rounds coordinates to 2 decimals (~1.1 km precision) for efficient local caching."""
    return f"{round(lat, 2):.2f},{round(lon, 2):.2f}"


def extract_orientation(text: Optional[str]) -> Optional[str]:
    """
    Extracts property solar exposure/orientation from listing text or descriptions.
    Returns normalized French cardinal direction: 'Sud', 'Sud-Est', 'Sud-Ouest',
    'Est', 'Ouest', 'Nord-Est', 'Nord-Ouest', 'Nord', or None if not mentioned.
    """
    if not text:
        return None

    clean_text = text.lower()

    # Regex patterns from most specific to general
    patterns: List[Tuple[str, str]] = [
        (r'\b(?:plein\s+sud[- ]ouest|expos[ée](?:e)?\s+plein\s+sud[- ]ouest|orient[ée](?:e)?\s+plein\s+sud[- ]ouest)\b', 'Sud-Ouest'),
        (r'\b(?:plein\s+sud[- ]est|expos[ée](?:e)?\s+plein\s+sud[- ]est|orient[ée](?:e)?\s+plein\s+sud[- ]est)\b', 'Sud-Est'),
        (r'\b(?:plein\s+nord[- ]ouest|expos[ée](?:e)?\s+plein\s+nord[- ]ouest|orient[ée](?:e)?\s+plein\s+nord[- ]ouest)\b', 'Nord-Ouest'),
        (r'\b(?:plein\s+nord[- ]est|expos[ée](?:e)?\s+plein\s+nord[- ]est|orient[ée](?:e)?\s+plein\s+nord[- ]est)\b', 'Nord-Est'),
        (r'\b(?:plein\s+sud|expos[ée](?:e)?\s+plein\s+sud|orient[ée](?:e)?\s+plein\s+sud)\b', 'Sud'),
        (r'\b(?:plein\s+ouest|expos[ée](?:e)?\s+plein\s+ouest|orient[ée](?:e)?\s+plein\s+ouest)\b', 'Ouest'),
        (r'\b(?:plein\s+est|expos[ée](?:e)?\s+plein\s+est|orient[ée](?:e)?\s+plein\s+est)\b', 'Est'),
        (r'\b(?:plein\s+nord|expos[ée](?:e)?\s+plein\s+nord|orient[ée](?:e)?\s+plein\s+nord)\b', 'Nord'),
        (r'\b(?:expos[ée](?:e)?|orient[ée](?:e)?|exposition|orientation)\s+(?:au\s+|en\s+|vers\s+le\s+)?sud[- ]ouest\b', 'Sud-Ouest'),
        (r'\b(?:expos[ée](?:e)?|orient[ée](?:e)?|exposition|orientation)\s+(?:au\s+|en\s+|vers\s+le\s+)?sud[- ]est\b', 'Sud-Est'),
        (r'\b(?:expos[ée](?:e)?|orient[ée](?:e)?|exposition|orientation)\s+(?:au\s+|en\s+|vers\s+le\s+)?nord[- ]ouest\b', 'Nord-Ouest'),
        (r'\b(?:expos[ée](?:e)?|orient[ée](?:e)?|exposition|orientation)\s+(?:au\s+|en\s+|vers\s+le\s+)?nord[- ]est\b', 'Nord-Est'),
        (r'\b(?:expos[ée](?:e)?|orient[ée](?:e)?|exposition|orientation)\s+(?:au\s+|en\s+|vers\s+le\s+)?sud\b', 'Sud'),
        (r'\b(?:expos[ée](?:e)?|orient[ée](?:e)?|exposition|orientation)\s+(?:à\s+l\'|a\s+l\'|vers\s+l\')?ouest\b', 'Ouest'),
        (r'\b(?:expos[ée](?:e)?|orient[ée](?:e)?|exposition|orientation)\s+(?:à\s+l\'|a\s+l\'|vers\s+l\')?est\b', 'Est'),
        (r'\b(?:expos[ée](?:e)?|orient[ée](?:e)?|exposition|orientation)\s+(?:au\s+|en\s+|vers\s+le\s+)?nord\b', 'Nord'),
        (r'\bexposition\s*:\s*sud[- ]ouest\b', 'Sud-Ouest'),
        (r'\bexposition\s*:\s*sud[- ]est\b', 'Sud-Est'),
        (r'\bexposition\s*:\s*nord[- ]ouest\b', 'Nord-Ouest'),
        (r'\bexposition\s*:\s*nord[- ]est\b', 'Nord-Est'),
        (r'\bexposition\s*:\s*sud\b', 'Sud'),
        (r'\bexposition\s*:\s*ouest\b', 'Ouest'),
        (r'\bexposition\s*:\s*est\b', 'Est'),
        (r'\bexposition\s*:\s*nord\b', 'Nord'),
    ]

    for pattern, orientation in patterns:
        if re.search(pattern, clean_text):
            return orientation

    return None


def get_orientation_efficiency_factor(orientation: Optional[str]) -> float:
    """Returns the solar efficiency multiplier for a given roof/property orientation."""
    if not orientation:
        return 1.0  # Assumes optimal south-facing roof by default

    o = orientation.strip().lower()
    if "sud-est" in o or "sud est" in o or "sud-ouest" in o or "sud ouest" in o:
        return 0.95
    if "sud" in o:
        return 1.00
    if "est" in o or "ouest" in o:
        return 0.82
    if "nord-est" in o or "nord est" in o or "nord-ouest" in o or "nord ouest" in o:
        return 0.65
    if "nord" in o:
        return 0.55

    return 1.0


def calculate_french_solar_baseline(lat: float, lon: float) -> Tuple[int, float, float]:
    """
    Algorithmic fallback for solar irradiance in France based on latitude/longitude climate gradients.
    Returns: (sunshine_hours_per_year, annual_irradiation_kwh_m2, annual_pv_yield_per_kwc)
    """
    # Latitude gradient: North France (lat ~51° -> ~1600h) to South France (lat ~43° -> ~2800h)
    clamped_lat = max(41.3, min(51.1, lat))
    clamped_lon = max(-5.0, min(9.6, lon))

    # Base formula calibrated on Météo France and PVGIS averages across 100+ French stations
    lat_factor = (51.1 - clamped_lat) / (51.1 - 41.3)  # 0.0 (North) to 1.0 (South/Corsica)
    lon_factor = (clamped_lon + 5.0) / 14.6            # 0.0 (West/Brittany) to 1.0 (East/Alps)

    # South-east / Mediterranean bonus
    med_bonus = 0.0
    if clamped_lat < 45.0 and clamped_lon > 3.0:
        med_bonus = (45.0 - clamped_lat) * 60.0

    sunshine_hours = int(1600 + (lat_factor * 1050) + (lon_factor * 100) + med_bonus)
    sunshine_hours = max(1500, min(2950, sunshine_hours))

    # Irradiation kWh/m²/year
    irradiation = round(1050.0 + (lat_factor * 600.0) + (lon_factor * 50.0) + (med_bonus * 0.3), 1)

    # PV yield kWh per 1 kWp installed (with standard 14% system loss and optimal tilt)
    pv_yield_per_kwc = round(irradiation * 0.86, 1)

    return sunshine_hours, irradiation, pv_yield_per_kwc


def fetch_pvgis_solar_data(lat: float, lon: float) -> Optional[Dict[str, Any]]:
    """
    Calls the EU Commission PVGIS API (v5.3) to retrieve accurate photovoltaic potential.
    """
    url = "https://re.jrc.ec.europa.eu/api/v5_3/PVcalc"
    params = {
        "lat": round(lat, 4),
        "lon": round(lon, 4),
        "peakpower": 1,
        "loss": 14,
        "optimalinclination": 1,
        "optimalangles": 1,
        "outputformat": "json"
    }
    headers = {"User-Agent": "ImmoBoussole/1.0 (Solar Analysis)"}

    try:
        res = httpx.get(url, params=params, headers=headers, timeout=8.0)
        res.raise_for_status()
        data = res.json()

        totals = data.get("outputs", {}).get("totals", {}).get("fixed", {})
        monthly = data.get("outputs", {}).get("monthly", {}).get("fixed", [])

        annual_production_1kwc = totals.get("E_y")
        annual_irradiation = totals.get("H(i)_y")
        optimal_tilt = totals.get("optimal_inclination")
        optimal_azimuth = totals.get("optimal_azimuth")

        if annual_production_1kwc is not None:
            # Sum sunshine duration if available across months
            monthly_data = []
            for m in monthly:
                monthly_data.append({
                    "month": m.get("month"),
                    "production_kwh": round(m.get("E_m", 0), 1),
                    "irradiation_kwh_m2": round(m.get("H(i)_m", 0), 1),
                    "sunshine_hours": round(m.get("SD_m", 0), 1) if m.get("SD_m") is not None else None,
                })

            return {
                "source": "pvgis",
                "annual_production_1kwc": float(annual_production_1kwc),
                "annual_irradiation_kwh_m2": float(annual_irradiation) if annual_irradiation else None,
                "optimal_tilt_deg": int(round(optimal_tilt)) if optimal_tilt is not None else 35,
                "optimal_azimuth_deg": int(round(optimal_azimuth)) if optimal_azimuth is not None else 0,
                "monthly": monthly_data,
            }
    except Exception as e:
        logger.debug(f"[Solar] PVGIS API request failed for ({lat}, {lon}): {e}")

    return None


def fetch_open_meteo_sunshine(lat: float, lon: float) -> Optional[int]:
    """
    Calls Open-Meteo historical / climate archive API to get annual sunshine hours.
    """
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": round(lat, 4),
        "longitude": round(lon, 4),
        "start_date": "2023-01-01",
        "end_date": "2023-12-31",
        "daily": "sunshine_duration",
        "timezone": "Europe/Paris"
    }
    headers = {"User-Agent": "ImmoBoussole/1.0"}

    try:
        res = httpx.get(url, params=params, headers=headers, timeout=6.0)
        res.raise_for_status()
        data = res.json()
        durations_sec = data.get("daily", {}).get("sunshine_duration", [])
        if durations_sec:
            total_sec = sum(d for d in durations_sec if d is not None)
            total_hours = int(round(total_sec / 3600.0))
            if 1200 <= total_hours <= 3300:
                return total_hours
    except Exception as e:
        logger.debug(f"[Solar] Open-Meteo sunshine fetch failed for ({lat}, {lon}): {e}")

    return None


def calculate_solar_potential(
    lat: float,
    lon: float,
    orientation: Optional[str] = None,
    property_type: Optional[str] = None,
    db: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Computes complete solar and photovoltaic potential for a given coordinate & property context.
    Uses memory cache and database cache when available.
    """
    geo_key = _get_geo_cache_key(lat, lon)

    # 1. Check in-memory cache for raw geo data
    geo_solar_base = _SOLAR_MEM_CACHE.get(geo_key)

    # 2. Check DB cache if available
    if geo_solar_base is None and db is not None:
        try:
            from app.models import SolarCache
            cached_row = db.query(SolarCache).filter(SolarCache.geo_key == geo_key).first()
            if cached_row and cached_row.data_json:
                geo_solar_base = json.loads(cached_row.data_json)
                _SOLAR_MEM_CACHE[geo_key] = geo_solar_base
        except Exception as e:
            logger.debug(f"[Solar] DB cache lookup error: {e}")

    # 3. Query external APIs if not cached
    if geo_solar_base is None:
        pvgis_data = fetch_pvgis_solar_data(lat, lon)
        open_meteo_sunshine = fetch_open_meteo_sunshine(lat, lon)
        baseline_sunshine, baseline_irrad, baseline_yield = calculate_french_solar_baseline(lat, lon)

        if pvgis_data:
            annual_pv_yield_1kwc = pvgis_data["annual_production_1kwc"]
            annual_irrad = pvgis_data.get("annual_irradiation_kwh_m2") or baseline_irrad
            optimal_tilt = pvgis_data.get("optimal_tilt_deg", 35)
            # Sunshine hours
            sunshine_h = open_meteo_sunshine or baseline_sunshine
            monthly = pvgis_data.get("monthly", [])
        else:
            annual_pv_yield_1kwc = baseline_yield
            annual_irrad = baseline_irrad
            optimal_tilt = 35
            sunshine_h = open_meteo_sunshine or baseline_sunshine
            monthly = []

        geo_solar_base = {
            "geo_key": geo_key,
            "latitude": round(lat, 4),
            "longitude": round(lon, 4),
            "sunshine_hours_per_year": int(sunshine_h),
            "solar_irradiation_kwh_m2": round(annual_irrad, 1),
            "pv_yield_per_kwc_annual": round(annual_pv_yield_1kwc, 1),
            "optimal_tilt_deg": optimal_tilt,
            "monthly": monthly,
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }

        _SOLAR_MEM_CACHE[geo_key] = geo_solar_base

        # Save to DB cache if available
        if db is not None:
            try:
                from app.models import SolarCache
                new_cache = SolarCache(
                    geo_key=geo_key,
                    data_json=json.dumps(geo_solar_base),
                    sunshine_hours=int(sunshine_h),
                    solar_irradiation=round(annual_irrad, 1),
                    pv_yield_per_kwc=round(annual_pv_yield_1kwc, 1),
                    updated_at=datetime.now(timezone.utc)
                )
                db.merge(new_cache)
                db.commit()
            except Exception as e:
                logger.debug(f"[Solar] DB cache write error: {e}")

    # 4. Contextualize with property-specific parameters (orientation & property type)
    eff_factor = get_orientation_efficiency_factor(orientation)
    base_yield_per_kwc = geo_solar_base["pv_yield_per_kwc_annual"]

    prod_3kwc = round(3.0 * base_yield_per_kwc * eff_factor)
    prod_6kwc = round(6.0 * base_yield_per_kwc * eff_factor)

    # Financial savings estimation (€/year)
    # Savings = (Production * SelfConsumptionRatio * GridTariff) + (Production * (1 - SelfConsumptionRatio) * SurplusTariff)
    price_per_kwh_blended = (RESIDENTIAL_SELF_CONSUMPTION_RATIO * GRID_ELEC_PRICE_KWH) + (
        (1.0 - RESIDENTIAL_SELF_CONSUMPTION_RATIO) * SURPLUS_FEED_IN_PRICE_KWH
    )
    savings_3kwc = round(prod_3kwc * price_per_kwh_blended)
    savings_6kwc = round(prod_6kwc * price_per_kwh_blended)

    # Solar score rating
    sunshine_hours = geo_solar_base["sunshine_hours_per_year"]
    if sunshine_hours >= 2350 or base_yield_per_kwc >= 1300:
        solar_score = "Exceptionnel"
        solar_score_class = "solar-exceptional"
        solar_stars = 4
    elif sunshine_hours >= 2000 or base_yield_per_kwc >= 1150:
        solar_score = "Très bon"
        solar_score_class = "solar-very-good"
        solar_stars = 3
    elif sunshine_hours >= 1700 or base_yield_per_kwc >= 950:
        solar_score = "Bon"
        solar_score_class = "solar-good"
        solar_stars = 2
    else:
        solar_score = "Moyen"
        solar_score_class = "solar-moderate"
        solar_stars = 1

    # Property type suitability
    p_type = (property_type or "").strip().lower()
    is_house = any(k in p_type for k in ["maison", "villa", "propriété", "ferme", "chalet", "pavillon", "corps de ferme", "demeure", "bastide", "longère", "mas"])
    is_apartment = any(k in p_type for k in ["appartement", "studio", "duplex", "loft", "triplex", "t1", "t2", "t3", "t4", "t5"])

    if is_house:
        suitability_label = "Idéal toiture individuelle"
        suitability_hint = "Projet photovoltaïque standard en toiture (accès direct et démarches simplifiées)."
    elif is_apartment:
        suitability_label = "Copropriété / Balcon"
        suitability_hint = "Installation possible sur toiture collective (accord AG requis) ou kit solaire de balcon."
    else:
        suitability_label = "Potentiel standard"
        suitability_hint = "Vérifier la configuration du toit ou de l'espace extérieur privatif."

    return {
        "sunshine_hours_per_year": sunshine_hours,
        "solar_irradiation_kwh_m2": geo_solar_base["solar_irradiation_kwh_m2"],
        "pv_yield_per_kwc_annual": base_yield_per_kwc,
        "optimal_tilt_deg": geo_solar_base.get("optimal_tilt_deg", 35),
        "detected_orientation": orientation,
        "orientation_efficiency_pct": int(round(eff_factor * 100)),
        "pv_production_3kwc": prod_3kwc,
        "pv_production_6kwc": prod_6kwc,
        "estimated_savings_3kwc": savings_3kwc,
        "estimated_savings_6kwc": savings_6kwc,
        "roof_surface_3kwc_m2": 15,
        "roof_surface_6kwc_m2": 30,
        "solar_score": solar_score,
        "solar_score_class": solar_score_class,
        "solar_stars": solar_stars,
        "is_house": is_house,
        "suitability_label": suitability_label,
        "suitability_hint": suitability_hint,
        "monthly": geo_solar_base.get("monthly", []),
    }
