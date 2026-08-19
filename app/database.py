"""
Database configuration and automatic schema migration for SQLite.
Since we don't use Alembic, this module handles ALTER TABLE migrations
so the existing DB survives model updates without needing to be deleted.
"""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import settings

engine = create_engine(
    settings.DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ─── Migration helpers ────────────────────────────────────────────────────────

# Each entry: (table, column_name, column_def)
# SQLite only supports ADD COLUMN, not MODIFY.
_MIGRATIONS = [
    # listings — new columns from v2
    ("listings", "original_url",        "TEXT"),
    ("listings", "city",                "TEXT"),
    ("listings", "price_per_sqm",       "REAL"),
    ("listings", "land_area",           "REAL"),
    ("listings", "rooms",               "INTEGER"),
    ("listings", "bedrooms",            "INTEGER"),
    ("listings", "floor",               "INTEGER"),
    ("listings", "total_floors",        "INTEGER"),
    ("listings", "building_year",       "INTEGER"),
    ("listings", "dpe_rating",          "TEXT"),
    ("listings", "ges_rating",          "TEXT"),
    ("listings", "land_tax",            "REAL"),
    ("listings", "charges",             "REAL"),
    ("listings", "agency_fee",          "REAL"),
    ("listings", "description_text",    "TEXT"),
    ("listings", "photos_local",        "TEXT"),
    ("listings", "original_photo_urls", "TEXT"),
    ("listings", "scraped_at",          "DATETIME"),
    ("listings", "is_duplicate",        "INTEGER DEFAULT 0"),
    ("listings", "duplicate_of_id",     "INTEGER"),
    # Allow external_id to be null (for manual imports)
    # SQLite can't change nullable; new rows simply pass NULL

    # search_queries — new columns from v2
    ("search_queries", "last_run",   "DATETIME"),
    ("search_queries", "created_at", "DATETIME"),

    # reviews table is entirely new (handled by create_all)

    # listings — new columns from v3 (LeBonCoin full characteristics)
    ("listings", "bathroom_count",       "INTEGER"),
    ("listings", "toilet_count",         "INTEGER"),
    ("listings", "property_type",        "TEXT"),
    ("listings", "condition",            "TEXT"),
    ("listings", "heating_type",         "TEXT"),
    ("listings", "heating_mode",         "TEXT"),
    ("listings", "kitchen_type",         "TEXT"),
    ("listings", "orientation",          "TEXT"),
    ("listings", "view",                 "TEXT"),
    ("listings", "cellar",               "INTEGER"),
    ("listings", "parking_count",        "INTEGER"),
    ("listings", "balcony",              "INTEGER"),
    ("listings", "balcony_area",         "REAL"),
    ("listings", "terrace",              "INTEGER"),
    ("listings", "terrace_area",         "REAL"),
    ("listings", "garden",               "INTEGER"),
    ("listings", "garden_area",          "REAL"),
    ("listings", "pool",                 "INTEGER"),
    ("listings", "elevator",             "INTEGER"),
    ("listings", "interphone",           "INTEGER"),
    ("listings", "guardian",             "INTEGER"),
    ("listings", "furnished",            "INTEGER"),
    ("listings", "dpe_value",            "REAL"),
    ("listings", "ges_value",            "REAL"),
    ("listings", "copropriete_lots",     "INTEGER"),
    ("listings", "procedure_syndic",     "INTEGER"),
    ("listings", "honoraires_a_charge",  "TEXT"),
    ("listings", "virtual_tour_url",     "TEXT"),
    
    # listings — SNCF Routing
    ("listings", "nearest_sncf_station", "TEXT"),
    ("listings", "walk_time_sncf",       "INTEGER"),
    ("listings", "bike_time_sncf",       "INTEGER"),
    ("listings", "car_time_sncf",        "INTEGER"),

    # listings — SNCF Routing Part 2 (Manual selection & second station)
    ("listings", "second_sncf_station", "TEXT"),
    ("listings", "walk_time_sncf_2",     "INTEGER"),
    ("listings", "bike_time_sncf_2",     "INTEGER"),
    ("listings", "car_time_sncf_2",      "INTEGER"),

    # users — new columns from v4
    ("users", "role",                    "TEXT DEFAULT 'user'"),

    # listings — geolocation coordinates v5
    ("listings", "latitude",             "REAL"),
    ("listings", "longitude",            "REAL"),

    # users — address and POI fields v5
    ("users", "work_address",            "TEXT"),
    ("users", "work_lat",                "REAL"),
    ("users", "work_lon",                "REAL"),
    ("users", "poi_json",                "TEXT"),

    # map_pins — shared user address pins v6
    ("map_pins", "title",                "TEXT NOT NULL DEFAULT ''"),
    ("map_pins", "address",              "TEXT NOT NULL DEFAULT ''"),
    ("map_pins", "lat",                  "REAL"),
    ("map_pins", "lon",                  "REAL"),
    ("map_pins", "created_by",           "TEXT NOT NULL DEFAULT ''"),
    ("map_pins", "created_at",           "DATETIME"),

    # listings — Géorisques report v7
    ("listings", "georisques_json",      "TEXT"),

    # listings — ReadySearch source tracking v8
    ("listings", "source_ready_search_id", "INTEGER"),
    ("listings", "source_criteria",        "TEXT"),

    # map_pins — nearby city metadata v9
    ("map_pins", "nearby_distance_km",     "REAL"),
    ("map_pins", "nearby_ref_commune",     "TEXT"),
    ("map_pins", "nearby_ref_cp",          "TEXT"),

    # users — Apprise notification URL v10
    ("users", "apprise_url",               "TEXT"),

    # users — Contact & SFR Identifiers v11
    ("users", "email",                     "TEXT"),
    ("users", "phone",                     "TEXT"),
    ("users", "sfr_identifier",            "TEXT"),
    ("users", "sfr_password",              "TEXT"),

    # map_pins — pin type v12
    ("map_pins", "pin_type",               "TEXT NOT NULL DEFAULT 'city'"),

    # listings — favorite listings v13
    ("listings", "is_favorite",            "BOOLEAN DEFAULT 0"),
    ("listings", "is_liked",               "BOOLEAN DEFAULT 0"),
    ("listings", "is_disliked",            "BOOLEAN DEFAULT 0"),

    # zone_rules — forbidden/allowed zones v14 (table is new, handled by create_all)
    # These entries are placeholders; the table is created by Base.metadata.create_all

    # global_settings — maintenance automation v15
    ("global_settings", "db_check_automate",  "BOOLEAN DEFAULT 0"),
    ("global_settings", "db_check_interval",  "TEXT DEFAULT '24h'"),
    ("global_settings", "db_repair_automate", "BOOLEAN DEFAULT 0"),
    ("global_settings", "db_repair_interval", "TEXT DEFAULT '24h'"),

    # global_settings — maintenance history v16
    ("global_settings", "last_global_check",  "TEXT"),
    ("global_settings", "last_checks_json",   "TEXT DEFAULT '{}'"),
    ("global_settings", "last_repairs_json",  "TEXT DEFAULT '{}'"),

    # global_settings - allowed departments v17
    ("global_settings", "allowed_departments", "TEXT"),

    # listings — to_visit flag v18
    ("listings", "to_visit",               "BOOLEAN DEFAULT 0"),

    # users — API key columns v19
    ("users", "api_key_hash",              "TEXT"),
    ("users", "can_create_api_key",        "BOOLEAN DEFAULT 0"),
    ("users", "api_key_last_used",         "DATETIME"),
    
    # listings — contact_made flag v20
    ("listings", "contact_made",           "BOOLEAN DEFAULT 0"),

    # visits — step_family and step columns v21
    ("visits", "step_family",              "TEXT"),
    ("visits", "step",                     "TEXT"),

    # listings — agent & agency link v22
    ("listings", "main_agent_id",          "INTEGER"),
    ("listings", "agency_id",             "INTEGER"),

    # visits — google_event_id v23
    ("visits", "google_event_id",          "TEXT"),

    # global_settings — google oauth fields v24
    ("global_settings", "google_oauth_credentials_json", "TEXT"),
    ("global_settings", "google_oauth_tokens_json",      "TEXT"),
    ("global_settings", "google_pilot_email",            "TEXT DEFAULT 'GOOGLE_ACCOUNT_EMAIL@gmail.com'"),

    # global_settings — scraping proxies v25
    ("global_settings", "scraping_proxies_json",         "TEXT"),

    # agencies & agents — google contact sync v26
    ("agencies", "google_contact_resource_name",         "TEXT"),
    ("agents", "google_contact_resource_name",           "TEXT"),

    # visit_contacts — agent link v27
    ("visit_contacts", "agent_id",                       "INTEGER"),

    # listings — last visit status v28
    ("listings", "last_visit_status",                   "TEXT"),

    # listings — address precision & override v29
    ("listings", "address",                             "TEXT"),
    ("listings", "postal_code",                         "TEXT"),
    ("listings", "address_precision",                   "TEXT DEFAULT 'city'"),
    ("listings", "manual_address_override",             "BOOLEAN DEFAULT 0"),
]



def run_migrations():
    """
    Applies Base.metadata.create_all and ADD COLUMN migrations to existing SQLite tables.
    Safe to run on every startup — skips columns that already exist.
    """
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:

        for table, column, col_def in _MIGRATIONS:
            # Check existing columns
            result = conn.execute(text(f"PRAGMA table_info({table})"))
            existing = {row[1] for row in result}

            if column not in existing:
                try:
                    conn.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
                    )
                    conn.commit()
                    print(f"[Migration] Added column '{column}' to '{table}'")
                except Exception as e:
                    print(f"[Migration] Warning: could not add '{column}' to '{table}': {e}")
            # else: column already exists, skip silently

        # Backfill price_per_sqm for listings where it's missing or 0
        try:
            conn.execute(
                text(
                    "UPDATE listings SET price_per_sqm = ROUND(1.0 * price / area, 2) "
                    "WHERE price IS NOT NULL AND price > 0 "
                    "AND area IS NOT NULL AND area > 0 "
                    "AND (price_per_sqm IS NULL OR price_per_sqm = 0)"
                )
            )
            conn.commit()
        except Exception as e:
            print(f"[Migration] Warning: could not backfill price_per_sqm: {e}")

        # Backfill step_family and step for existing visits
        try:
            conn.execute(text("UPDATE visits SET step_family = 'visite', step = '1ere_visite' WHERE (step_family IS NULL OR step_family = '') AND visit_type = 'visite'"))
            conn.execute(text("UPDATE visits SET step_family = 'visite', step = 'contre_visite' WHERE (step_family IS NULL OR step_family = '') AND visit_type = 'contre_visite'"))
            conn.execute(text("UPDATE visits SET step_family = 'contact', step = 'appel_direct' WHERE (step_family IS NULL OR step_family = '') AND visit_type IN ('contact_agence', 'contact_proprio')"))
            conn.execute(text("UPDATE visits SET step_family = 'contact', step = 'relance_sans_reponse' WHERE (step_family IS NULL OR step_family = '') AND visit_type = 'relance_agence'"))
            conn.execute(text("UPDATE visits SET step_family = 'cloture', step = 'offre_refusee' WHERE (step_family IS NULL OR step_family = '') AND visit_type = 'reponse_negative'"))
            conn.execute(text("UPDATE visits SET step_family = 'visite', step = '1ere_visite' WHERE step_family IS NULL OR step_family = ''"))
            conn.commit()
        except Exception as e:
            print(f"[Migration] Warning: could not backfill visit step_family: {e}")

