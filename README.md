# Reconcile.dev

**A W3C-compliant Reconciliation Service API for connecting datasets.**
Final project for CM3070 (BSc Computer Science, University of London), by Mohammed Hisham.

Reconcile.dev matches messy place names such as `"Lahroe"`, `"Karrachi"` or `"London, CA"` to the
correct GeoNames record. It is a FastAPI service backed by PostgreSQL that follows the
[W3C Reconciliation Service API](https://reconciliation-api.github.io/specs/latest/), so it plugs
straight into tools like OpenRefine.

## What it does

| Step | Description |
|------|-------------|
| 1. Ingest | Loads 234,416 GeoNames places (`cities500.txt`), sorted by population, into PostgreSQL |
| 2. Index | B-tree on `lower(name)`, GIN trigram index (`pg_trgm`) on `name`, B-tree on country code |
| 3. Normalise | Lowercases input and strips accents (Unicode NFKD), punctuation and extra spaces |
| 4. Exact match | Fast case-insensitive lookup; the most populous place wins ties |
| 5. Fuzzy match | Trigram candidate retrieval, then weighted RapidFuzz scoring with a length penalty |
| 6. Respond | De-duplicated, ranked results in W3C Reconciliation API format |

Endpoints include batch reconciliation (`/query`), entity suggestions (`/suggest/entity`),
entity previews (`/preview`) and a health check (`/health`). Optional country-code filtering
resolves ambiguous names (for example "London" with `CA` returns London, Ontario).

## Headline results

Measured with `scripts/evaluate.py` against the full 234,416-row database.

| Metric | Result | Target |
|--------|--------|--------|
| Exact match accuracy | 98% | > 95% ✅ |
| Fuzzy match F1 (threshold 0.85) | 0.901 | > 0.85 ✅ |
| Mean Reciprocal Rank | 0.770 | — |
| Exact match response time | 1.0 ms avg | < 200 ms ✅ |
| Fuzzy match response time | 697.6 ms avg | < 200 ms ❌ |

Top-1 accuracy by distortion type: character doubling 99.2%, character deletion 87.2%,
transposition 77.4%, word truncation 23.3% (51.5% top-5).

Switching fuzzy retrieval to the index-backed `%` operator is the planned next step to bring
fuzzy query times under the 200 ms target.

## Screenshots

### System architecture
![System architecture](docs/images/architecture.jpg)

### Interactive API documentation (`/docs`)
![FastAPI auto-generated API docs](docs/images/api-docs.png)

### Reconciling place names in OpenRefine
Exact matches score 1.0; misspellings such as "Lahroe" and "Karrachi" are matched to the correct city.

![OpenRefine reconciliation results](docs/images/openrefine-results.png)
![OpenRefine fuzzy matches](docs/images/openrefine-fuzzy.png)

### Server log during reconciliation
![Server terminal log](docs/images/server-log.png)

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
app\main.py          FastAPI app entry point
app\routers\         W3C reconciliation endpoints
app\matcher.py       Normalisation, exact and fuzzy matching engine
app\database.py      PostgreSQL connection
app\schemas.py       Request/response models
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
