from datetime import datetime

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    environment: str


class DbLatencyResponse(BaseModel):
    """Answer to "is the database reachable, and how far away is it?".

    Deliberately four plain fields. No host, no region, no connection
    string, no driver version, no row counts, no table names — the whole
    point is that this is safe to leave reachable, and anything that
    describes the database beyond "it answered in N ms" is not needed to
    tell whether it is up.
    """

    ok: bool
    database: str
    latency_ms: int
    timestamp: datetime
