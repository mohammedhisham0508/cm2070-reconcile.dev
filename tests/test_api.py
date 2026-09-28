import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.matcher import normalise, score_candidate

client = TestClient(app)


# ── Manifest Tests ────────────────────────────────────────────────────────────

class TestManifest:
    """Tests for GET / — the service manifest endpoint."""

    def test_manifest_returns_200(self):
        response = client.get("/")
        assert response.status_code == 200

    def test_manifest_has_required_fields(self):
        data = client.get("/").json()
        assert "name" in data
        assert "versions" in data
        assert "defaultTypes" in data
        assert "identifierSpace" in data
        assert "schemaSpace" in data

    def test_manifest_version_is_02(self):
        data = client.get("/").json()
        assert "0.2" in data["versions"]

    def test_manifest_has_default_type(self):
        data = client.get("/").json()
        assert len(data["defaultTypes"]) > 0
        assert data["defaultTypes"][0]["id"] == "/place"


# ── Query Endpoint Tests ──────────────────────────────────────────────────────

class TestQueryEndpoint:
    """Tests for POST /query — the main reconciliation endpoint."""

    def _query(self, q: str, limit: int = 5) -> dict:
        """Helper to send a single query and get back the result list."""
        response = client.post("/query", json={
            "queries": {
                "q0": {"query": q, "limit": limit}
            }
        })
        assert response.status_code == 200
        return response.json()["q0"]["result"]

    # Format tests
    def test_response_has_correct_structure(self):
        result = self._query("London")
        assert isinstance(result, list)

    def test_each_candidate_has_required_fields(self):
        result = self._query("London")
        if result:
            c = result[0]
            assert "id" in c
            assert "name" in c
            assert "score" in c
            assert "match" in c
            assert "type" in c

    def test_scores_are_between_0_and_1(self):
        result = self._query("London")
        for c in result:
            assert 0.0 <= c["score"] <= 1.0, f"Score out of range: {c['score']}"

    def test_results_sorted_by_score_descending(self):
        result = self._query("Paris")
        scores = [c["score"] for c in result]
        assert scores == sorted(scores, reverse=True)

    def test_limit_is_respected(self):
        result = self._query("London", limit=3)
        assert len(result) <= 3

    # Exact match tests
    def test_exact_match_returns_score_1(self):
        result = self._query("London")
        if result and result[0]["name"].lower() == "london":
            assert result[0]["score"] == 1.0

    def test_exact_match_sets_match_true(self):
        result = self._query("London")
        if result and result[0]["score"] == 1.0:
            assert result[0]["match"] is True

    # Fuzzy match tests
    def test_typo_still_finds_correct_city(self):
        result = self._query("Lahroe")   # typo for Lahore
        names = [c["name"] for c in result]
        assert "Lahore" in names, f"Expected Lahore in results, got: {names}"

    def test_typo_score_below_1(self):
        result = self._query("Lahroe")
        if result:
            assert result[0]["score"] < 1.0

    def test_typo_match_flag_is_false(self):
        result = self._query("Lahroe")
        if result:
            # Typos should not auto-match — human should confirm
            assert result[0]["match"] is False

    def test_partial_name_finds_city(self):
        result = self._query("New York")
        names = [c["name"] for c in result]
        assert any("New York" in n for n in names), f"Expected New York variant, got: {names}"

    # Nonsense query tests
    def test_nonsense_query_returns_empty_or_low_score(self):
        result = self._query("xqzptlmno")
        # Either returns nothing, or all scores are low
        for c in result:
            assert c["score"] < 0.7, f"Unexpected high score for nonsense query: {c}"

    # Batch query test
    def test_batch_query_returns_all_keys(self):
        response = client.post("/query", json={
            "queries": {
                "q0": {"query": "London"},
                "q1": {"query": "Paris"},
                "q2": {"query": "Berlin"},
            }
        })
        data = response.json()
        assert "q0" in data
        assert "q1" in data
        assert "q2" in data



class TestSuggestEndpoint:
    """Tests for GET /suggest/entity — autocomplete endpoint."""

    def test_suggest_returns_200(self):
        response = client.get("/suggest/entity?prefix=Lon")
        assert response.status_code == 200

    def test_suggest_returns_result_key(self):
        data = client.get("/suggest/entity?prefix=Lon").json()
        assert "result" in data

    def test_suggest_short_prefix_returns_empty(self):
        data = client.get("/suggest/entity?prefix=L").json()
        assert data["result"] == []

    def test_suggest_results_have_id_and_name(self):
        data = client.get("/suggest/entity?prefix=Par").json()
        for r in data["result"]:
            assert "id" in r
            assert "name" in r


# ── Normaliser Unit Tests ─────────────────────────────────────────────────────

class TestNormaliser:
    """Unit tests for the normalise() function in matcher.py."""

    def test_lowercase(self):
        assert normalise("LAHORE") == "lahore"

    def test_strips_whitespace(self):
        assert normalise("  London  ") == "london"

    def test_strips_punctuation(self):
        assert normalise("New York (City)") == "new york city"

    def test_collapses_spaces(self):
        assert normalise("New  York   City") == "new york city"

    def test_empty_string(self):
        assert normalise("") == ""

    def test_unicode_normalisation(self):
        # Lāhore with macron should normalise to lahore
        result = normalise("Lāhore")
        assert result == "lahore"


# ── Scorer Unit Tests ─────────────────────────────────────────────────────────

class TestScorer:
    """Unit tests for the score_candidate() function."""

    def test_identical_strings_score_1(self):
        assert score_candidate("Lahore", "Lahore") == 1.0

    def test_similar_strings_score_high(self):
        score = score_candidate("Lahroe", "Lahore")
        assert score > 0.85, f"Expected > 0.85, got {score}"

    def test_different_strings_score_low(self):
        score = score_candidate("London", "Tokyo")
        assert score < 0.5, f"Expected < 0.5, got {score}"

    def test_partial_match_scores_reasonably(self):
        score = score_candidate("New York", "New York City")
        assert score > 0.75, f"Expected > 0.75, got {score}"
