"""
Database configuration and automatic schema migration for SQLite.
Since we don't use Alembic, this module handles ALTER TABLE migrations
so the existing DB survives model updates without needing to be deleted.
"""
from sqlalchemy import create_engine, text, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, declarative_base
import sqlite3
from app.config import settings

engine = create_engine(
    settings.DATABASE_URL, connect_args={"check_same_thread": False}
)


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """
    Configures high-performance SQLite PRAGMAs on every new database connection.
    Enables WAL mode, fast synchronous writes, 64MB memory cache, 256MB memory mapped I/O,
    busy timeout, and foreign key constraints.
    """
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode = WAL;")
            cursor.execute("PRAGMA synchronous = NORMAL;")
            cursor.execute("PRAGMA cache_size = -64000;")  # 64MB cache
            cursor.execute("PRAGMA temp_store = MEMORY;")
            cursor.execute("PRAGMA mmap_size = 268435456;")  # 256MB mmap
            cursor.execute("PRAGMA busy_timeout = 5000;")
            cursor.execute("PRAGMA foreign_keys = ON;")
        except Exception as e:
            print(f"[Database] Warning: could not set SQLite PRAGMAs: {e}")
        finally:
            cursor.close()


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

    # listings — cadastral parcel v30
    ("listings", "cadastral_parcel",                    "TEXT"),

    # global_settings — public services integrations v30
    ("global_settings", "public_services_json",         "TEXT DEFAULT '{}'"),

    # global_settings — automated nightly maintenance & storage optimization v31
    ("global_settings", "auto_maintenance_enabled",        "BOOLEAN DEFAULT 1"),
    ("global_settings", "auto_maintenance_time",           "TEXT DEFAULT '03:30'"),
    ("global_settings", "auto_maintenance_purge_rejected", "BOOLEAN DEFAULT 0"),
    ("global_settings", "last_storage_cleanup",            "TEXT"),
    ("global_settings", "last_db_optimization",           "TEXT"),
    ("global_settings", "last_maintenance_metrics_json",   "TEXT DEFAULT '{}'"),

    # users — missing location notification & session tracking v32
    ("users", "last_seen_missing_loc_count",               "INTEGER DEFAULT 0"),
    ("users", "missing_loc_snooze_until",                  "DATETIME"),
    ("users", "last_login_at",                             "DATETIME"),

    # users — auto read notifications policy v34
    ("users", "auto_read_after_days",                      "INTEGER DEFAULT 30"),

    # listings — repair tags (data quality errors) v33
    ("listings", "repair_tags",                            "TEXT"),

    # listings — solar & exposure v35
    ("listings", "orientation",                            "TEXT"),
    ("listings", "solar_json",                             "TEXT"),

    # visits — collaboration & short URL access token v36
    ("visits", "access_token",                             "TEXT"),
    ("visits", "meeting_address",                          "TEXT"),
    ("visits", "instructions",                             "TEXT"),
    ("visits", "participants_json",                        "TEXT"),

    # visit_questions — unified property listing_id & answered_by v37
    ("visit_questions", "listing_id",                      "INTEGER"),
    ("visit_questions", "answered_by",                     "TEXT"),

    # visit_inclusions — furniture & service contracts v37
    ("visit_inclusions", "negotiation_status",             "TEXT DEFAULT 'inclus_prix_negocie'"),

    # global_questions & visit_questions — language code v38
    ("global_questions", "language",                       "TEXT DEFAULT 'fr'"),
    ("visit_questions", "language",                        "TEXT DEFAULT 'fr'"),

    # visit_questions — answered_at timestamp and respondent_type v39
    ("visit_questions", "answered_at",                     "DATETIME"),
    ("visit_questions", "respondent_type",                 "TEXT"),
]



def run_migrations():
    """
    Applies Base.metadata.create_all and ADD COLUMN migrations to existing SQLite tables.
    Also ensures high-performance indexes are created.
    Safe to run on every startup — skips columns and indexes that already exist.
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

        # Strategic Indexes for High Performance Queries
        _INDEXES = [
            ("idx_listings_status", "CREATE INDEX IF NOT EXISTS idx_listings_status ON listings(status);"),
            ("idx_listings_is_duplicate", "CREATE INDEX IF NOT EXISTS idx_listings_is_duplicate ON listings(is_duplicate);"),
            ("idx_listings_duplicate_of_id", "CREATE INDEX IF NOT EXISTS idx_listings_duplicate_of_id ON listings(duplicate_of_id);"),
            ("idx_listings_to_visit", "CREATE INDEX IF NOT EXISTS idx_listings_to_visit ON listings(to_visit);"),
            ("idx_listings_is_favorite", "CREATE INDEX IF NOT EXISTS idx_listings_is_favorite ON listings(is_favorite);"),
            ("idx_listings_is_liked", "CREATE INDEX IF NOT EXISTS idx_listings_is_liked ON listings(is_liked);"),
            ("idx_listings_is_disliked", "CREATE INDEX IF NOT EXISTS idx_listings_is_disliked ON listings(is_disliked);"),
            ("idx_listings_source", "CREATE INDEX IF NOT EXISTS idx_listings_source ON listings(source);"),
            ("idx_listings_city", "CREATE INDEX IF NOT EXISTS idx_listings_city ON listings(city);"),
            ("idx_listings_price", "CREATE INDEX IF NOT EXISTS idx_listings_price ON listings(price);"),
            ("idx_listings_area", "CREATE INDEX IF NOT EXISTS idx_listings_area ON listings(area);"),
            ("idx_listings_rooms", "CREATE INDEX IF NOT EXISTS idx_listings_rooms ON listings(rooms);"),
            ("idx_listings_price_per_sqm", "CREATE INDEX IF NOT EXISTS idx_listings_price_per_sqm ON listings(price_per_sqm);"),
            ("idx_listings_date_added", "CREATE INDEX IF NOT EXISTS idx_listings_date_added ON listings(date_added DESC);"),
            ("idx_visits_listing_id", "CREATE INDEX IF NOT EXISTS idx_visits_listing_id ON visits(listing_id);"),
            ("idx_visits_scheduled_at", "CREATE INDEX IF NOT EXISTS idx_visits_scheduled_at ON visits(scheduled_at);"),
            ("idx_visits_access_token", "CREATE INDEX IF NOT EXISTS idx_visits_access_token ON visits(access_token);"),
            ("idx_visit_questions_listing_id", "CREATE INDEX IF NOT EXISTS idx_visit_questions_listing_id ON visit_questions(listing_id);"),
            ("idx_visit_questions_visit_id", "CREATE INDEX IF NOT EXISTS idx_visit_questions_visit_id ON visit_questions(visit_id);"),
            ("idx_visit_questions_language", "CREATE INDEX IF NOT EXISTS idx_visit_questions_language ON visit_questions(language);"),
            ("idx_global_questions_category", "CREATE INDEX IF NOT EXISTS idx_global_questions_category ON global_questions(category);"),
            ("idx_global_questions_language", "CREATE INDEX IF NOT EXISTS idx_global_questions_language ON global_questions(language);"),
            ("idx_visit_inclusions_listing_id", "CREATE INDEX IF NOT EXISTS idx_visit_inclusions_listing_id ON visit_inclusions(listing_id);"),
            ("idx_visit_inclusions_visit_id", "CREATE INDEX IF NOT EXISTS idx_visit_inclusions_visit_id ON visit_inclusions(visit_id);"),
            ("idx_visit_media_visit_id", "CREATE INDEX IF NOT EXISTS idx_visit_media_visit_id ON visit_media(visit_id);"),
            ("idx_visit_media_listing_id", "CREATE INDEX IF NOT EXISTS idx_visit_media_listing_id ON visit_media(listing_id);"),
            ("idx_visit_question_media_qid", "CREATE INDEX IF NOT EXISTS idx_visit_question_media_qid ON visit_question_media(question_id);"),
            ("idx_visit_question_media_mid", "CREATE INDEX IF NOT EXISTS idx_visit_question_media_mid ON visit_question_media(media_id);"),
            ("idx_notifications_user_id", "CREATE INDEX IF NOT EXISTS idx_notifications_user_id ON notifications(user_id);"),
            ("idx_notifications_is_read", "CREATE INDEX IF NOT EXISTS idx_notifications_is_read ON notifications(is_read);"),
            ("idx_notifications_created_at", "CREATE INDEX IF NOT EXISTS idx_notifications_created_at ON notifications(created_at DESC);"),
        ]

        for idx_name, idx_sql in _INDEXES:
            try:
                conn.execute(text(idx_sql))
                conn.commit()
            except Exception as e:
                print(f"[Migration] Warning: could not create index '{idx_name}': {e}")

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

        # Backfill listing_id for visit_questions where it's missing
        try:
            conn.execute(text("UPDATE visit_questions SET listing_id = (SELECT listing_id FROM visits WHERE visits.id = visit_questions.visit_id) WHERE listing_id IS NULL"))
            conn.commit()
        except Exception as e:
            print(f"[Migration] Warning: could not backfill visit_questions.listing_id: {e}")

    # Auto-seed platform master question catalog if needed
    try:
        from app.visit_templates import seed_global_questions
        with SessionLocal() as db_session:
            seed_global_questions(db_session)
    except Exception as e:
        print(f"[Migration] Note: could not auto-seed global questions: {e}")

    # Auto-repair corrupted text (mojibake) in visit_inclusions and visit_questions
    # Auto-repair corrupted text (mojibake) in visit_inclusions and visit_questions
    try:
        from app.csv_service import fix_mojibake
        with engine.connect() as conn:
            # 1. Repair visit_inclusions
            try:
                inc_rows = conn.execute(text(
                    "SELECT id, title, room, variation_notes, condition, provider_name, equipment_included, transfer_status, negotiation_status, notes "
                    "FROM visit_inclusions"
                )).fetchall()

                for r in inc_rows:
                    inc_id = r[0]
                    updates = {}
                    cols = ["title", "room", "variation_notes", "condition", "provider_name", "equipment_included", "transfer_status", "negotiation_status", "notes"]
                    for idx, col in enumerate(cols, start=1):
                        val = r[idx]
                        if val and isinstance(val, str):
                            fixed = fix_mojibake(val)
                            if col == "negotiation_status":
                                c_neg = (fixed or "").lower().strip()
                                if "negoc" in c_neg or "disc" in c_neg or "cours" in c_neg:
                                    fixed = "en_discussion"
                                elif "excl" in c_neg or "refus" in c_neg:
                                    fixed = "exclu_vendeur"
                                elif "opt" in c_neg or "payan" in c_neg or "suppl" in c_neg:
                                    fixed = "option_payante"
                                elif "inclus" in c_neg or "prix" in c_neg or "accord" in c_neg:
                                    fixed = "inclus_prix_negocie"
                            if fixed != val:
                                updates[col] = fixed

                    if updates:
                        set_clauses = ", ".join([f"{c} = :{c}" for c in updates.keys()])
                        updates["id"] = inc_id
                        conn.execute(text(f"UPDATE visit_inclusions SET {set_clauses} WHERE id = :id"), updates)
                conn.commit()
            except Exception as e_inc:
                print(f"[Migration] Note: could not execute visit_inclusions mojibake repair: {e_inc}")

            # 2. Repair visit_questions
            try:
                q_rows = conn.execute(text(
                    "SELECT id, question_text, answer_text, themes_json, created_by, answered_by FROM visit_questions"
                )).fetchall()
                for r in q_rows:
                    q_id = r[0]
                    q_updates = {}
                    for idx, col in enumerate(["question_text", "answer_text", "themes_json", "created_by", "answered_by"], start=1):
                        val = r[idx]
                        if val and isinstance(val, str):
                            fixed = fix_mojibake(val)
                            if fixed != val:
                                q_updates[col] = fixed
                    if q_updates:
                        set_clauses = ", ".join([f"{c} = :{c}" for c in q_updates.keys()])
                        q_updates["id"] = q_id
                        conn.execute(text(f"UPDATE visit_questions SET {set_clauses} WHERE id = :id"), q_updates)
                conn.commit()
            except Exception as e_q:
                print(f"[Migration] Note: could not execute visit_questions mojibake repair: {e_q}")
    except Exception as e:
        print(f"[Migration] Note: could not execute mojibake text repair: {e}")


