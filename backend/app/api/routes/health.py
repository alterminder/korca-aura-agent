from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import DBDep

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    service: str | None = None
    db: str | None = None


class StatsResponse(BaseModel):
    documents: int
    users: int
    tickets: int
    clients: int


class RecentActivityItem(BaseModel):
    subject: str | None
    ticket_id: int | str | None
    expert_name: str | None
    expert_email: str | None
    routed_at: str | None
    client_name: str | None
    outcome: str | None
    confirmed: bool | None


class ExpertLoadItem(BaseModel):
    name: str | None
    email: str | None
    ticket_count: int


class ClientLoadItem(BaseModel):
    name: str | None
    domain: str | None
    ticket_count: int


class NeedsReviewResponse(BaseModel):
    staged: int


@router.get("/health")
async def health() -> HealthResponse:
    return HealthResponse(status="ok", service="korca")


@router.get("/health/db")
async def health_db(db: DBDep) -> HealthResponse:
    await db.run("RETURN 1")
    return HealthResponse(status="ok", db="connected")


@router.get("/stats")
async def stats(db: DBDep) -> StatsResponse:
    doc_res = await db.run("MATCH (d:Document) RETURN count(d) AS n")
    user_res = await db.run("MATCH (u:User) RETURN count(u) AS n")
    ticket_res = await db.run("MATCH (t:Ticket) RETURN count(t) AS n")
    client_res = await db.run("MATCH (c:Client) RETURN count(c) AS n")
    doc_record = await doc_res.single()
    user_record = await user_res.single()
    ticket_record = await ticket_res.single()
    client_record = await client_res.single()
    return StatsResponse(
        documents=doc_record["n"] if doc_record else 0,
        users=user_record["n"] if user_record else 0,
        tickets=ticket_record["n"] if ticket_record else 0,
        clients=client_record["n"] if client_record else 0,
    )


@router.get("/stats/recent-activity")
async def recent_activity(db: DBDep) -> list[RecentActivityItem]:
    result = await db.run(
        """
        MATCH (t:Ticket)-[:HAS_ROUTING_EVENT]->(e:RoutingEvent)
        WITH t, e
        ORDER BY e.created_at DESC
        WITH t, collect(e)[0] AS latest_event
        OPTIONAL MATCH (c:Client)<-[:FROM]-(t)
        RETURN t.subject AS subject,
               t.id AS ticket_id,
               latest_event.suggested_name AS expert_name,
               latest_event.suggested_email AS expert_email,
               latest_event.created_at AS routed_at,
               c.name AS client_name,
               latest_event.outcome AS outcome,
               latest_event.outcome = 'correct' AS confirmed
        ORDER BY latest_event.created_at DESC
        LIMIT 15
        """
    )
    records = await result.data()
    return [
        RecentActivityItem(
            subject=r["subject"],
            ticket_id=r["ticket_id"],
            expert_name=r["expert_name"],
            expert_email=r["expert_email"],
            routed_at=r["routed_at"],
            client_name=r["client_name"],
            outcome=r["outcome"],
            confirmed=r["confirmed"],
        )
        for r in records
    ]


@router.get("/stats/expert-load")
async def expert_load(db: DBDep) -> list[ExpertLoadItem]:
    result = await db.run(
        """
        MATCH (u:User)-[:ASSIGNED_TO]->(t:Ticket)
        RETURN u.name AS name,
               u.email AS email,
               count(t) AS ticket_count
        ORDER BY ticket_count DESC
        LIMIT 8
        """
    )
    records = await result.data()
    return [
        ExpertLoadItem(name=r["name"], email=r["email"], ticket_count=r["ticket_count"])
        for r in records
    ]


@router.get("/stats/client-load")
async def client_load(db: DBDep) -> list[ClientLoadItem]:
    result = await db.run(
        """
        MATCH (:User)-[:ASSIGNED_TO]->(t:Ticket)-[:FROM]->(c:Client)
        RETURN c.name AS name,
               c.domain AS domain,
               count(t) AS ticket_count
        ORDER BY ticket_count DESC
        LIMIT 8
        """
    )
    records = await result.data()
    return [
        ClientLoadItem(name=r["name"], domain=r["domain"], ticket_count=r["ticket_count"])
        for r in records
    ]


@router.get("/stats/needs-review")
async def needs_review(db: DBDep) -> NeedsReviewResponse:
    staged_res = await db.run(
        "MATCH (t:Ticket) WHERE t.ingest_status = 'staged' RETURN count(t) AS n"
    )
    staged_rec = await staged_res.single()
    return NeedsReviewResponse(staged=staged_rec["n"] if staged_rec else 0)
