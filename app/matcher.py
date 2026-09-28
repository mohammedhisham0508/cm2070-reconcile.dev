import re
import unicodedata
from typing import Optional
from rapidfuzz import fuzz, distance
from sqlalchemy.orm import Session
from sqlalchemy import text


TRIGRAM_CANDIDATE_LIMIT = 30   
TRIGRAM_THRESHOLD       = 0.20 
MIN_SCORE_THRESHOLD     = 0.78 
AUTO_MATCH_THRESHOLD    = 0.95 
AUTO_MATCH_GAP          = 0.10 
FIELD_MATCH_BONUS       = 0.04 



def normalise(query: str) -> str:

    s = query.lower().strip()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^\w\s\-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def exact_match(db: Session, query_norm: str) -> Optional[dict]:
    
    sql = text("""
        SELECT geonameid, name, country_code, population
        FROM   places
        WHERE  lower(name)      = :q
           OR  lower(asciiname) = :q
        ORDER  BY population DESC
        LIMIT  1
    """)
    row = db.execute(sql, {"q": query_norm}).fetchone()
    if not row:
        return None
    return {
        "id":           str(row.geonameid),
        "name":         row.name,
        "country_code": row.country_code,
        "population":   row.population or 0,
        "final_score":  1.0,
        "match":        True,
    }

def get_trigram_candidates(db: Session, query_norm: str) -> list[dict]:
    """
    Use pg_trgm similarity() to retrieve the most similar place names.

    We avoid the %% operator (causes SQLAlchemy escaping issues on Windows)
    and use similarity() > threshold instead. The GIN index makes this fast
    even on 234k rows.
    """
    sql = text("""
        SELECT
            geonameid,
            name,
            asciiname,
            country_code,
            population,
            GREATEST(
                similarity(lower(name),      :q),
                similarity(lower(asciiname), :q)
            ) AS trgm_score
        FROM places
        WHERE similarity(lower(name),      :q) > :thresh
           OR similarity(lower(asciiname), :q) > :thresh
        ORDER BY trgm_score DESC
        LIMIT :lim
    """)
    rows = db.execute(sql, {
        "q":      query_norm,
        "thresh": TRIGRAM_THRESHOLD,
        "lim":    TRIGRAM_CANDIDATE_LIMIT,
    }).fetchall()

    return [
        {
            "id":           str(row.geonameid),
            "name":         row.name,
            "asciiname":    row.asciiname or row.name,
            "country_code": row.country_code or "",
            "population":   row.population or 0,
        }
        for row in rows
    ]


def score_candidate(query_original: str, candidate_name: str) -> float:
    q   = query_original.strip()
    c   = candidate_name.strip()
    q_l = len(q)
    c_l = len(c)

    ratio = fuzz.ratio(q, c)            / 100.0
    sort  = fuzz.token_sort_ratio(q, c) / 100.0
    jw    = distance.JaroWinkler.normalized_similarity(q, c)
    base = max(ratio, sort) * 0.65 + jw * 0.35

    # Bidirectional length penalty
    if q_l > 0 and c_l > 0:
        len_ratio = min(q_l, c_l) / max(q_l, c_l)
        if len_ratio < 0.85:
            penalty = 0.55 + (len_ratio * 0.529)
            base = base * penalty

    return round(base, 4)


def deduplicate(candidates: list[dict]) -> list[dict]:
    
    seen   = {}   
    result = []

    for c in candidates:
        key = c["name"].lower().strip()
        if key not in seen:
            seen[key] = c
            result.append(c)
        else:
            # Keep the one with higher population
            if c.get("population", 0) > seen[key].get("population", 0):
                seen[key].update(c)

    return result


def apply_auto_match(candidates: list[dict]) -> list[dict]:
   
    if not candidates:
        return candidates

    top    = candidates[0]["final_score"]
    second = candidates[1]["final_score"] if len(candidates) > 1 else 0.0

    for i, c in enumerate(candidates):
        if i == 0 and top >= AUTO_MATCH_THRESHOLD and (top - second) >= AUTO_MATCH_GAP:
            c["match"] = True
        elif i == 0 and top == 1.0:
            c["match"] = True
        else:
            c["match"] = False

    return candidates
def reconcile(
    db:             Session,
    query_original: str,
    limit:          int = 5,
    country_filter: Optional[str] = None,
) -> list[dict]:
   
    query_norm = normalise(query_original)
    if not query_norm:
        return []

    exact = exact_match(db, query_norm)
    if exact:
        if country_filter and exact["country_code"]:
            if exact["country_code"].upper() == country_filter.upper():
                exact["final_score"] = min(1.0, exact["final_score"] + FIELD_MATCH_BONUS)
        return [exact]
    candidates = get_trigram_candidates(db, query_norm)
    if not candidates:
        return []
    for c in candidates:
        raw = score_candidate(query_original, c["name"])

        if country_filter and c["country_code"]:
            if c["country_code"].upper() == country_filter.upper():
                raw = min(1.0, raw + FIELD_MATCH_BONUS)

        c["final_score"] = raw
    candidates.sort(
        key=lambda x: (x["final_score"], x.get("population", 0)),
        reverse=True
    )

    candidates = deduplicate(candidates)
    candidates = [c for c in candidates if c["final_score"] >= MIN_SCORE_THRESHOLD]

    candidates = apply_auto_match(candidates)

    return candidates[:limit]