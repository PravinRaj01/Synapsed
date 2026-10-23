import mimetypes
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import PurePath
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pgvector import Vector
from pydantic import BaseModel, Field

from ai_pipeline.embedder import embed_texts
from app.api.common import require_campaign as _require_campaign
from app.core import storage
from app.core.rate_limit import limited
from app.core.auth import AuthUser, current_user
from app.core.config import get_settings
from app.core.database import user_tx
from app.ingestion import parsers, web
from app.ingestion.chunking import chunk_text
from app.ingestion.parsers import IngestError, ToolMissing
from app.ingestion.pipeline import Prepared, parse_upload, prepare, resolve_source_type

router = APIRouter(prefix="/api/v1", tags=["ingestion"])


class IngestedResource(BaseModel):
    id: UUID
    title: str
    status: str
    duplicate: bool
    chars: int
    language: str | None
    redactions: dict[str, int]
    pii_notice: str | None = None  # set when names may remain; review before approving


class IngestResponse(BaseModel):
    resources: list[IngestedResource]
    duplicates: int


UPLOAD_URL_SECONDS = 900


class UploadRequest(BaseModel):
    campaign_id: UUID
    filename: str = Field(min_length=1, max_length=255)
    size: int = Field(ge=1)


class UploadTicket(BaseModel):
    key: str  # send this back to /ingest/stored after the PUT
    url: str  # PUT the raw file bytes here (no auth header, no multipart)
    expires_in: int
    max_bytes: int


class StoredIngestRequest(BaseModel):
    campaign_id: UUID
    key: str = Field(min_length=1, max_length=600)
    source_type: str | None = None
    text_column: str | None = None
    segment_column: str | None = None


class ResearchRequest(BaseModel):
    campaign_id: UUID
    query: str = Field(min_length=3, max_length=200)
    max_results: int = Field(5, ge=1, le=10)


class ResearchResult(BaseModel):
    url: str
    title: str
    resource: IngestedResource | None = None
    skipped: str | None = None


def _insert_resource(
    conn: psycopg.Connection, *, campaign_id: UUID, title: str, source_type: str,
    prepared: Prepared, segment_id: UUID | None = None, source_url: str | None = None,
    storage_path: str | None = None, summary: str | None = None,
) -> IngestedResource:
    """Insert a staged resource, or report the existing one when the content is a duplicate."""
    row = conn.execute(
        """insert into resources (campaign_id, title, source_type, source_url, storage_path, content,
                                  summary, language, segment_id, content_hash, pii_redacted, pii_note)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           on conflict (campaign_id, content_hash) do nothing
           returning id, status""",
        (campaign_id, title, source_type, source_url, storage_path, prepared.text, summary,
         prepared.language, segment_id, prepared.hash, prepared.pii_redacted, prepared.pii_note),
    ).fetchone()
    duplicate = row is None
    if duplicate:
        row = conn.execute(
            "select id, status from resources where campaign_id = %s and content_hash = %s",
            (campaign_id, prepared.hash),
        ).fetchone()
    return IngestedResource(
        id=row["id"], title=title, status=row["status"], duplicate=duplicate,
        chars=len(prepared.text), language=prepared.language, redactions=prepared.redactions,
        pii_notice=prepared.pii_note,
    )


def _segment_ids(conn: psycopg.Connection, campaign_id: UUID) -> dict[str, UUID]:
    rows = conn.execute("select id, name from segments where campaign_id = %s", (campaign_id,)).fetchall()
    return {r["name"].lower(): r["id"] for r in rows}


def _stage(
    user: AuthUser, campaign_id: UUID, data: bytes, filename: str, key: str, source_type: str | None,
    text_column: str | None, segment_column: str | None, *, already_stored: bool,
) -> IngestResponse:
    """Parse, scrub and stage a file's content; keep the file in storage unless nothing new came of it."""
    try:
        kind = parsers.detect_kind(filename)
        stype = resolve_source_type(kind, source_type)
        prepared = [
            (item, prepare(item.text))
            for item in parse_upload(data, filename, kind, text_column, segment_column)
        ]
    except ToolMissing as exc:
        raise HTTPException(503, str(exc)) from exc
    except IngestError as exc:
        if already_stored:
            storage.delete_object(key)  # the user cannot use this file as it is
        raise HTTPException(422, str(exc)) from exc

    if not already_stored:
        storage.upload_bytes(key, data, mimetypes.guess_type(filename)[0] or "application/octet-stream")

    results: list[IngestedResource] = []
    with user_tx(user.id) as conn:
        segments = _segment_ids(conn, campaign_id)
        for item, prep in prepared:
            segment_id = segments.get(item.segment.lower()) if item.segment else None
            results.append(
                _insert_resource(
                    conn, campaign_id=campaign_id, title=item.title, source_type=stype, prepared=prep,
                    segment_id=segment_id, storage_path=key, summary=web.summarize(prep.text),
                )
            )
    duplicates = sum(r.duplicate for r in results)
    if duplicates == len(results):  # nothing new was stored, so drop the orphaned upload
        storage.delete_object(key)
    return IngestResponse(resources=results, duplicates=duplicates)


@router.post("/ingest", response_model=IngestResponse)
def ingest(
    campaign_id: UUID = Form(...),
    file: UploadFile = File(...),
    source_type: str | None = Form(None),
    text_column: str | None = Form(None),
    segment_column: str | None = Form(None),
    user: AuthUser = Depends(limited("ingest")),
) -> IngestResponse:
    """Parse, scrub and stage an uploaded file. Nothing is embedded until it is approved.

    The body must fit the host's request limit (4.5 MB on Vercel); larger files use /uploads.
    """
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    _require_campaign(user.id, campaign_id)

    data = file.file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(413, f"File is larger than {get_settings().max_upload_mb} MB")
    filename = PurePath(file.filename or "upload").name
    key = f"{campaign_id}/{uuid.uuid4().hex}/{filename}"
    return _stage(user, campaign_id, data, filename, key, source_type, text_column, segment_column,
                  already_stored=False)


@router.post("/uploads", response_model=UploadTicket)
def create_upload(req: UploadRequest, user: AuthUser = Depends(current_user)) -> UploadTicket:
    """Check a file before it is sent, and return a presigned URL the browser can PUT it to."""
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    _require_campaign(user.id, req.campaign_id)
    filename = PurePath(req.filename).name
    try:
        parsers.detect_kind(filename)
    except IngestError as exc:
        raise HTTPException(422, str(exc)) from exc
    if req.size > max_bytes:
        raise HTTPException(413, f"File is larger than {get_settings().max_upload_mb} MB")
    key = f"{req.campaign_id}/{uuid.uuid4().hex}/{filename}"
    return UploadTicket(
        key=key, url=storage.presigned_url(key, UPLOAD_URL_SECONDS, "put_object"),
        expires_in=UPLOAD_URL_SECONDS, max_bytes=max_bytes,
    )


@router.post("/ingest/stored", response_model=IngestResponse)
def ingest_stored(req: StoredIngestRequest, user: AuthUser = Depends(limited("ingest"))) -> IngestResponse:
    """Stage a file the browser already uploaded to the key from /uploads."""
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    _require_campaign(user.id, req.campaign_id)
    if not req.key.startswith(f"{req.campaign_id}/") or ".." in req.key:
        raise HTTPException(403, "That upload does not belong to this campaign")
    size = storage.object_size(req.key)
    if size is None:
        raise HTTPException(404, "No uploaded file found for that key. Upload it first.")
    if size > max_bytes:
        storage.delete_object(req.key)
        raise HTTPException(413, f"File is larger than {get_settings().max_upload_mb} MB")
    filename = PurePath(req.key).name
    return _stage(user, req.campaign_id, storage.download_bytes(req.key), filename, req.key,
                  req.source_type, req.text_column, req.segment_column, already_stored=True)


@router.get("/resources")
def list_resources(campaign_id: UUID, status: str | None = None, user: AuthUser = Depends(current_user)):
    with user_tx(user.id) as conn:
        return conn.execute(
            """select r.id, r.title, r.source_type, r.source_url, r.language, r.status,
                      r.pii_redacted, r.pii_note, r.summary, r.created_at, length(r.content) as chars,
                      (select count(*) from resource_chunks c where c.resource_id = r.id) as chunk_count
               from resources r
               where r.campaign_id = %s and (%s::text is null or r.status = %s)
               order by r.created_at desc limit 500""",
            (campaign_id, status, status),
        ).fetchall()


@router.post("/resources/{resource_id}/approve")
def approve_resource(resource_id: UUID, user: AuthUser = Depends(limited("approve"))):
    """Chunk and embed a staged resource, then mark it approved so agents and chat can use it."""
    with user_tx(user.id) as conn:
        row = conn.execute("select status, content from resources where id = %s", (resource_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Resource not found")
    if row["status"] != "staged":
        raise HTTPException(409, f"Resource is already {row['status']}")

    chunks = chunk_text(row["content"])
    try:  # embed outside any transaction: the API call can take a while
        vectors = embed_texts([c.content for c in chunks])
    except Exception as exc:
        raise HTTPException(502, "The embedding service is unavailable. Try again shortly.") from exc

    with user_tx(user.id) as conn:
        updated = conn.execute(
            "update resources set status = 'approved' where id = %s and status = 'staged' returning id",
            (resource_id,),
        ).fetchone()
        if updated is None:
            raise HTTPException(409, "Resource changed while it was being embedded")
        with conn.cursor() as cur:
            cur.executemany(
                """insert into resource_chunks (resource_id, chunk_index, content, start_offset, end_offset, embedding)
                   values (%s, %s, %s, %s, %s, %s)""",
                [(resource_id, c.index, c.content, c.start, c.end, Vector(v)) for c, v in zip(chunks, vectors)],
            )
    return {"id": resource_id, "status": "approved", "chunks": len(chunks)}


@router.post("/resources/{resource_id}/reject")
def reject_resource(resource_id: UUID, user: AuthUser = Depends(current_user)):
    with user_tx(user.id) as conn:
        row = conn.execute(
            "update resources set status = 'rejected' where id = %s and status = 'staged' returning id",
            (resource_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "No staged resource with that id")
    return {"id": resource_id, "status": "rejected"}


@router.post("/research", response_model=list[ResearchResult])
def research(req: ResearchRequest, user: AuthUser = Depends(limited("research"))) -> list[ResearchResult]:
    """Search the web and stage readable results. The PM approves what is worth keeping."""
    _require_campaign(user.id, req.campaign_id)
    try:
        hits = web.search_web(req.query, req.max_results)
    except Exception as exc:
        raise HTTPException(502, "Web search is unavailable. Try again shortly.") from exc

    with ThreadPoolExecutor(max_workers=4) as pool:
        pages = list(pool.map(lambda h: web.fetch_page(h.url), hits))

    results: list[ResearchResult] = []
    with user_tx(user.id) as conn:
        for hit, page in zip(hits, pages):
            if page is None:
                results.append(ResearchResult(url=hit.url, title=hit.title, skipped="could not be read"))
                continue
            try:
                prep = prepare(page.text[:60_000])
            except IngestError:
                results.append(ResearchResult(url=hit.url, title=hit.title, skipped="no text"))
                continue
            resource = _insert_resource(
                conn, campaign_id=req.campaign_id, title=page.title, source_type="web_scrape",
                prepared=prep, source_url=page.url, summary=web.summarize(prep.text),
            )
            results.append(ResearchResult(url=page.url, title=page.title, resource=resource))
    return results
