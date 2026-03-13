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
]


def run_migrations():
    """
    Applies ADD COLUMN migrations to existing SQLite tables.
    Safe to run on every startup — skips columns that already exist.
    """
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
