
import os
import sys
import time
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/reconcile_dev"
)

GEONAMES_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "cities500.txt")

MAX_ROWS = None


COLUMN_NAMES = [
    "geonameid",       
    "name",           
    "asciiname",      
    "alternatenames",  
    "latitude",        
    "longitude",      
    "feature_class",   
    "feature_code",  
    "country_code",   
    "cc2",            
    "admin1",         
    "admin2",         
    "admin3",       
    "admin4",   
    "population",     
    "elevation",       
    "dem",             
    "timezone",     
    "modified",        
]

KEEP_COLUMNS = [
    "geonameid",
    "name",
    "asciiname",
    "country_code",
    "population",
    "latitude",
    "longitude",
]


def main():
    print("=" * 55)
    print("  Reconcile.dev — GeoNames Ingestion Script")
    print("=" * 55)

    if not os.path.exists(GEONAMES_FILE):
        print(f"\nERROR: File not found: {GEONAMES_FILE}")
        print("\nFix:")
        print("  1. Download cities500.zip from:")
        print("     https://download.geonames.org/export/dump/cities500.zip")
        print("  2. Unzip it — you get cities500.txt")
        print("  3. Move cities500.txt into the data/ folder of this project")
        sys.exit(1)

    # ── Load the file ──────────────────────────────────────────────────────────
    print(f"\nReading: {GEONAMES_FILE}")
    start = time.time()

    df = pd.read_csv(
        GEONAMES_FILE,
        sep="\t",
        header=None,
        names=COLUMN_NAMES,
        low_memory=False,
        on_bad_lines="skip",
    )

    print(f"  Total rows in file: {len(df):,}")

    df = df[KEEP_COLUMNS].copy()
    df["geonameid"]    = pd.to_numeric(df["geonameid"],  errors="coerce")
    df["population"]   = pd.to_numeric(df["population"], errors="coerce").fillna(0).astype(int)
    df["latitude"]     = pd.to_numeric(df["latitude"],   errors="coerce")
    df["longitude"]    = pd.to_numeric(df["longitude"],  errors="coerce")
    df["name"]         = df["name"].fillna("").astype(str).str.strip()
    df["asciiname"]    = df["asciiname"].fillna("").astype(str).str.strip()
    df["country_code"] = df["country_code"].fillna("").astype(str).str.strip()
    df = df.sort_values("population", ascending=False)
    if MAX_ROWS:
        df = df.head(MAX_ROWS)
        print(f"  Loading top {MAX_ROWS:,} rows by population (prototype mode)")
    else:
        print(f"  Loading all {len(df):,} rows (full mode)")

    # Drop rows with no name or no valid ID
    df = df[(df["name"] != "") & (df["geonameid"].notna())]
    df["geonameid"] = df["geonameid"].astype(int)

    print(f"  Rows after cleaning: {len(df):,}")
    print(f"  File read in {time.time() - start:.1f}s")

    # ── Connect to PostgreSQL ──────────────────────────────────────────────────
    print(f"\nConnecting to database...")
    try:
        engine = create_engine(DATABASE_URL)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("  Connected successfully")
    except Exception as e:
        print(f"\nERROR: Could not connect to database.")
        print(f"  {e}")
        print("\nMake sure:")
        print("  - PostgreSQL is running")
        print("  - The database 'reconcile_dev' exists")
        print("  - Your .env file has the correct DATABASE_URL")
        sys.exit(1)

    # ── Enable pg_trgm extension ───────────────────────────────────────────────
    print("\nEnabling pg_trgm extension...")
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        conn.commit()
    print("  pg_trgm ready")

    # ── Create the places table ────────────────────────────────────────────────
    print("\nCreating places table...")
    create_table_sql = text("""
        DROP TABLE IF EXISTS places;
        CREATE TABLE places (
            geonameid    INTEGER PRIMARY KEY,
            name         TEXT NOT NULL,
            asciiname    TEXT,
            country_code CHAR(2),
            population   BIGINT DEFAULT 0,
            latitude     NUMERIC(10, 7),
            longitude    NUMERIC(10, 7)
        );
    """)
    with engine.connect() as conn:
        conn.execute(create_table_sql)
        conn.commit()
    print("  Table created")

    # ── Load data ──────────────────────────────────────────────────────────────
    print(f"\nLoading {len(df):,} rows into PostgreSQL...")
    start = time.time()

    df.to_sql(
        "places",
        engine,
        if_exists="append",
        index=False,
        method="multi",
        chunksize=1000,
    )

    elapsed = time.time() - start
    print(f"  Loaded {len(df):,} rows in {elapsed:.1f}s")

    # ── Create indexes ─────────────────────────────────────────────────────────
    print("\nCreating indexes (this may take a moment)...")
    start = time.time()

    index_sql = [
        "CREATE INDEX IF NOT EXISTS idx_places_name ON places (lower(name))",

        "CREATE INDEX IF NOT EXISTS idx_places_ascii ON places (lower(asciiname))",

        "CREATE INDEX IF NOT EXISTS idx_places_trgm ON places USING GIN (name gin_trgm_ops)",

        "CREATE INDEX IF NOT EXISTS idx_places_country ON places (country_code)",
    ]

    with engine.connect() as conn:
        for sql in index_sql:
            conn.execute(text(sql))
            print(f"  Created: {sql.split('idx_')[1].split(' ')[0]}")
        conn.commit()

    print(f"  All indexes created in {time.time() - start:.1f}s")

    # ── Verify ─────────────────────────────────────────────────────────────────
    print("\nVerifying...")
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM places")).scalar()
        top_global = conn.execute(
            text("SELECT geonameid, name, country_code, population FROM places ORDER BY population DESC LIMIT 5")
        ).fetchall()

        spot_check = conn.execute(text("""
            SELECT geonameid, name, country_code, population
            FROM places
            WHERE lower(name) IN (
                'singapore','lahore','karachi','islamabad',
                'london','manchester','edinburgh','kuala lumpur'
            )
            ORDER BY population DESC
        """)).fetchall()

    print(f"  Total rows in database: {count:,}")

    print(f"\n  Top 5 cities globally by population:")
    for row in top_global:
        print(f"    {row.geonameid:>10}  {row.name:<30}  {row.country_code}  ({row.population:,})")

    print(f"\n  Spot-check — key cities for this project:")
    found     = [row.name for row in spot_check]
    expected  = ["Singapore","Lahore","Karachi","Islamabad",
                 "London","Manchester","Edinburgh","Kuala Lumpur"]
    for city in expected:
        status = "✓" if city in found else "✗ MISSING"
        print(f"    {status}  {city}")

    if len(found) < len(expected):
        print("\n  Note: missing cities may not be in cities500 subset or")
        print("  spelled differently in GeoNames. Check the data if needed.")

    print("\n" + "=" * 55)
    print("  Ingestion complete. You can now start the API.")
    print("  Run:  uvicorn app.main:app --reload")
    print("=" * 55 + "\n")


if __name__ == "__main__":
    main()
