# Reconcile.dev

Reconcile.dev is a FastAPI service that reconciles place names against
GeoNames data. It supports exact and fuzzy matching, batch queries, entity
suggestions, and W3C Reconciliation API-compatible responses.

## Requirements

- Python 3.9 or newer
- PostgreSQL 13 or newer
- The GeoNames `cities500.txt` dataset

## Setup

### 1. Create a PostgreSQL database

Create a database named `reconcile_dev`:

```sql
CREATE DATABASE reconcile_dev;
```

The ingestion script also enables PostgreSQL's `pg_trgm` extension. The
database user must be allowed to create extensions, or an administrator can
run this first:

```sql
\c reconcile_dev
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

### 2. Create and activate a virtual environment

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install --only-binary=:all: -r requirements.txt
```

Windows Command Prompt:

```bat
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install --only-binary=:all: -r requirements.txt
```

### 3. Configure the database connection

Copy `.env.example` to `.env` and update the connection string:

```powershell
Copy-Item .env.example .env
```

Set `DATABASE_URL` in `.env` using this format:

```text
DATABASE_URL=postgresql+psycopg2://USER:PASSWORD@HOST:5432/reconcile_dev
```

Do not commit `.env`.

### 4. Download and ingest GeoNames data

Download `cities500.zip` from
https://download.geonames.org/export/dump/cities500.zip, extract
`cities500.txt`, and place it in `data\`.

Then run:

```powershell
python scripts\ingest.py
```

The ingestion process replaces the `places` table, loads the dataset, and
creates the indexes used by reconciliation queries. Re-run it whenever the
source dataset changes.

## Run the API

Start the development server from the project root:

```powershell
uvicorn app.main:app --reload
```

The service is available at http://127.0.0.1:8000.

Useful URLs:

- Health check: http://127.0.0.1:8000/health
- Interactive API docs: http://127.0.0.1:8000/docs
- OpenAPI schema: http://127.0.0.1:8000/openapi.json

## API examples

### Batch reconciliation

```powershell
curl.exe -X POST http://127.0.0.1:8000/query `
  -H "Content-Type: application/json" `
  -d '{"queries":{"q0":{"query":"Lahroe","limit":5},"q1":{"query":"London","limit":5}}}'
```

### Suggestions

```powershell
curl.exe "http://127.0.0.1:8000/suggest/entity?prefix=Lon"
```

### Entity preview

```powershell
curl.exe "http://127.0.0.1:8000/preview?id=2643743"
```

## Tests

Tests use the configured PostgreSQL database and expect the `places` table to
be populated. After ingestion, run:

```powershell
pytest tests -q
```

## Evaluation

To measure matching precision, recall, F1, MRR, and response time against the
populated database:

```powershell
python scripts\evaluate.py
```

The evaluation report is written to `data\eval_results.json`.

## Project layout

```text
app\                 FastAPI application and matching logic
scripts\             Dataset ingestion and evaluation utilities
tests\               API and matcher tests
data\cities500.txt   GeoNames input dataset (download separately)
requirements.txt     Python dependencies
.env.example         Database configuration template
```

## Notes

- `cities500.txt` is not committed by design because it is a large external
  dataset.
- The service uses PostgreSQL-specific `pg_trgm` similarity functions.
- The ingestion script drops and recreates the `places` table. Back up any
  existing data before running it in a shared environment.
