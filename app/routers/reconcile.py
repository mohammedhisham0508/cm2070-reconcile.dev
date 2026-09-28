from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import get_db
from app.schemas import (
    ServiceManifest,
    BatchQueryRequest,
    Candidate,
    EntityType,
    QueryResult,
)
from app.matcher import reconcile

router = APIRouter()

ENTITY_TYPE = [EntityType(id="/place", name="Place")]

@router.get("/", response_model=ServiceManifest)
def get_manifest():
   
    return ServiceManifest()


@router.post("/")
async def post_manifest_or_query(request: Request, db: Session = Depends(get_db)):
  
    import json
    import logging

    logger = logging.getLogger("reconcile")
    queries_raw = None

    body_bytes = await request.body()
    content_type = request.headers.get("content-type", "")

    logger.info(f"POST / content-type: {content_type}")
    logger.info(f"POST / body (first 500 chars): {body_bytes[:500]}")
    if "application/x-www-form-urlencoded" in content_type or "form" in content_type:
        try:
            form = await request.form()
            logger.info(f"POST / form keys: {list(form.keys())}")
            if "queries" in form:
                raw_str = form["queries"]
                logger.info(f"POST / queries value: {raw_str[:200]}")
                queries_raw = json.loads(raw_str)
        except Exception as e:
            logger.error(f"POST / form parse error: {e}")

    if queries_raw is None:
        try:
            body_json = json.loads(body_bytes)
            if "queries" in body_json:
                q = body_json["queries"]
                queries_raw = json.loads(q) if isinstance(q, str) else q
                logger.info(f"POST / parsed as JSON, keys: {list(queries_raw.keys())}")
        except Exception as e:
            logger.error(f"POST / JSON parse error: {e}")
    if queries_raw is None:
        try:
            parsed = json.loads(body_bytes)
            if parsed and all(isinstance(v, dict) and "query" in v
                              for v in parsed.values()):
                queries_raw = parsed
                logger.info(f"POST / parsed raw body as queries dict")
        except Exception:
            pass
    if queries_raw is None and body_bytes:
        try:
            from urllib.parse import parse_qs, unquote_plus
            decoded = body_bytes.decode("utf-8")
            params = parse_qs(decoded)
            logger.info(f"POST / URL-decoded params keys: {list(params.keys())}")
            if "queries" in params:
                queries_raw = json.loads(params["queries"][0])
                logger.info(f"POST / parsed via manual URL decode")
        except Exception as e:
            logger.error(f"POST / manual URL decode error: {e}")

    if not queries_raw:
        logger.info("POST / no queries found, returning manifest")
        return ServiceManifest()

    logger.info(f"POST / processing {len(queries_raw)} queries: {list(queries_raw.keys())}")

    from app.schemas import Candidate, EntityType
    entity_type = [EntityType(id="/place", name="Place")]
    response = {}

    for query_id, query_obj in queries_raw.items():
        if isinstance(query_obj, str):
            query_obj = json.loads(query_obj)

        query_str      = query_obj.get("query", "")
        limit          = int(query_obj.get("limit", 5))
        country_filter = None

        if not query_str:
            response[query_id] = {"result": []}
            continue

        matches = reconcile(
            db=db,
            query_original=query_str,
            limit=limit,
            country_filter=country_filter
        )

        candidates = [
            Candidate(
                id=m["id"],
                name=m["name"],
                score=m["final_score"],
                match=m.get("match", False),
                type=entity_type,
            )
            for m in matches
        ]

        response[query_id] = {"result": [c.model_dump() for c in candidates]}
        logger.info(f"  {query_id}: '{query_str}' → {len(candidates)} candidates")

    return response


@router.post("/query")
def query_endpoint(request: BatchQueryRequest, db: Session = Depends(get_db)):
    response = {}

    for query_id, query_obj in request.queries.items():

        country_filter = None
        if query_obj.type:
            country_filter = query_obj.type if len(query_obj.type) == 2 else None

        # Run the matching engine
        matches = reconcile(
            db=db,
            query_original=query_obj.query,
            limit=query_obj.limit,
            country_filter=country_filter
        )

        # Format each match as a W3C Candidate
        candidates = [
            Candidate(
                id=m["id"],
                name=m["name"],
                score=m["final_score"],
                match=m.get("match", False),
                type=ENTITY_TYPE,
            )
            for m in matches
        ]

        response[query_id] = QueryResult(result=candidates)

    # Return as plain dict — FastAPI will serialise it to JSON
    return {qid: qr.model_dump() for qid, qr in response.items()}

@router.get("/suggest/entity")
def suggest_entity(
    prefix: str  = Query(default="", description="Partial string typed by the user"),
    q:      str  = Query(default="", description="Alias for prefix (used by some clients)"),
    cursor: int  = Query(default=0),
    db: Session  = Depends(get_db)
):
    
    search_term = prefix or q
    if not search_term or len(search_term) < 2:
        return {"result": []}

    sql = text("""
        SELECT geonameid, name, country_code, population
        FROM places
        WHERE lower(name) LIKE lower(:prefix)
        ORDER BY population DESC
        LIMIT 10
    """)
    rows = db.execute(sql, {"prefix": f"{search_term.lower()}%"}).fetchall()

    results = [
        {
            "id":          str(row.geonameid),
            "name":        row.name,
            "description": f"{row.country_code or ''} | Pop: {row.population or 0:,}"
        }
        for row in rows
    ]

    return {"result": results}


# ── GET /preview — Entity Preview (Phase 2) ──────────────────────────────────

@router.get("/preview")
def preview_entity(id: str = Query(...), db: Session = Depends(get_db)):
    sql = text("""
        SELECT geonameid, name, country_code, population, latitude, longitude
        FROM places
        WHERE geonameid = :gid
        LIMIT 1
    """)
    row = db.execute(sql, {"gid": int(id)}).fetchone()

    if not row:
        return JSONResponse(status_code=404, content={"error": "Entity not found"})

    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; padding: 10px; font-size: 13px;">
        <h3 style="margin: 0 0 8px 0;">{row.name}</h3>
        <table>
            <tr><td><b>GeoNames ID:</b></td><td>{row.geonameid}</td></tr>
            <tr><td><b>Country:</b></td><td>{row.country_code or 'N/A'}</td></tr>
            <tr><td><b>Population:</b></td><td>{row.population or 0:,}</td></tr>
            <tr><td><b>Coordinates:</b></td><td>{row.latitude}, {row.longitude}</td></tr>
        </table>
        <p>
            <a href="https://www.geonames.org/{row.geonameid}" target="_blank">
                View on GeoNames ↗
            </a>
        </p>
    </body>
    </html>
    """
    return JSONResponse(content={"html": html})
