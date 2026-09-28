
from pydantic import BaseModel, Field
from typing import Optional

class ReconciliationQuery(BaseModel):
   
    query: str = Field(..., description="The string to reconcile against the dataset")
    limit: int = Field(default=5, ge=1, le=20, description="Max number of candidates to return")
    type:  Optional[str] = Field(default=None, description="Entity type filter (e.g. /place)")


class BatchQueryRequest(BaseModel):

    queries: dict[str, ReconciliationQuery]

class EntityType(BaseModel):
    """The type of a matched entity. Required field in W3C response."""
    id:   str = "/place"
    name: str = "Place"


class Candidate(BaseModel):
   
    id:    str
    name:  str
    score: float
    match: bool
    type:  list[EntityType]


class QueryResult(BaseModel):
   
    result: list[Candidate]
class ServiceManifest(BaseModel):
   
    versions:            list[str] = ["0.2"]
    name:                str       = "Reconcile.dev — GeoNames Geographic Reconciliation"
    identifierSpace:     str       = "http://www.geonames.org/ontology#"
    schemaSpace:         str       = "http://www.geonames.org/ontology#"
    defaultTypes:        list[EntityType] = [EntityType()]
    view:                dict      = {"url": "https://www.geonames.org/{{id}}"}
