"""Ingestion endpoints against a real Neon database.

Storage, embeddings and the web are mocked; auth is overridden with a chosen user id.
Skipped unless DATABASE_URL and DATABASE_URL_ADMIN are set. Test workspaces are deleted afterwards.
"""

from types import SimpleNamespace
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.api import ingestion as api
from app.core import database
from app.core.auth import AuthUser, current_user
from app.core.config import Settings, get_settings
from app.ingestion import web
from app.main import app

settings = get_settings()
pytestmark = pytest.mark.skipif(
    not (settings.database_url and settings.database_url_admin),
    reason="DATABASE_URL and DATABASE_URL_ADMIN are not set",
)

UNIT = [1.0] + [0.0] * 767


@pytest.fixture
def who():
    return SimpleNamespace(id=uuid4())


@pytest.fixture
def client(who, monkeypatch):
    app.dependency_overrides[current_user] = lambda: AuthUser(id=who.id)
    uploads, deletes = [], []
    monkeypatch.setattr(api.storage, "upload_bytes", lambda key, data, ct="": uploads.append(key) or key)
    monkeypatch.setattr(api.storage, "delete_object", lambda key: deletes.append(key))
    with TestClient(app) as c:  # runs the lifespan, which opens the connection pool
        c.uploads, c.deletes = uploads, deletes
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def campaign(client, who):
    with database.user_tx(who.id) as conn:
        ws = conn.execute("select create_workspace('Ingest test', 'Acme', 'SaaS') as id").fetchone()["id"]
        cid = conn.execute(
            "insert into campaigns (workspace_id, name) values (%s, 'C1') returning id", (ws,)
        ).fetchone()["id"]
        sid = conn.execute(
            "insert into segments (campaign_id, name, tier, weight) values (%s, 'Enterprise', 'enterprise', 3) returning id",
            (cid,),
        ).fetchone()["id"]
    yield SimpleNamespace(id=cid, enterprise=sid)
    with psycopg.connect(settings.database_url_admin) as admin:
        admin.execute("delete from workspaces where id = %s", (ws,))


def post_file(client, campaign_id, name, content, **form):
    return client.post(
        "/api/v1/ingest", data={"campaign_id": str(campaign_id), **form}, files={"file": (name, content)}
    )


def fetch(who, sql, *params):
    with database.user_tx(who.id) as conn:
        return conn.execute(sql, params).fetchall()


NOTE = (
    "Interview with Sarah Connor (sarah@acme.io, +60 12-345 6789). "
    "She said the monthly export takes ten minutes and often times out. "
) * 3


def test_ingest_scrubs_pii_and_stages(client, campaign, who):
    r = post_file(client, campaign.id, "interview.txt", NOTE.encode())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["duplicates"] == 0 and len(body["resources"]) == 1
    res = body["resources"][0]
    assert res["status"] == "staged" and res["language"] == "en" and res["redactions"]
    row = fetch(who, "select content, source_type, pii_redacted, storage_path from resources where id = %s", res["id"])[0]
    assert "sarah@acme.io" not in row["content"] and "Sarah Connor" not in row["content"]
    assert row["source_type"] == "transcript" and row["pii_redacted"] is True
    assert row["storage_path"].startswith(f"{campaign.id}/") and client.uploads == [row["storage_path"]]
    assert fetch(who, "select count(*) as n from resource_chunks")[0]["n"] == 0  # nothing embedded yet


def test_same_content_is_a_duplicate_and_the_upload_is_dropped(client, campaign, who):
    first = post_file(client, campaign.id, "a.txt", NOTE.encode()).json()["resources"][0]
    # The hash ignores case and spacing. Only a non-name word is changed: the NER step
    # does not recognise names in ALL CAPS, which would change the scrubbed text.
    again = post_file(client, campaign.id, "b.txt", NOTE.replace("export", "EXPORT").replace(" ", "  ").encode())
    assert again.json()["duplicates"] == 1 and again.json()["resources"][0]["id"] == first["id"]
    assert fetch(who, "select count(*) as n from resources")[0]["n"] == 1
    assert len(client.deletes) == 1 and client.deletes[0] == client.uploads[1]


def test_csv_is_split_by_segment_and_matched_to_segments(client, campaign, who):
    csv_bytes = (
        "tier,comment\nEnterprise,Reports time out on big accounts\nFree,Onboarding was confusing\n"
        "Enterprise,SSO login keeps failing\n"
    ).encode()
    r = post_file(client, campaign.id, "survey.csv", csv_bytes, segment_column="tier", text_column="comment")
    assert r.status_code == 200, r.text
    assert sorted(x["title"] for x in r.json()["resources"]) == ["survey.csv — Enterprise", "survey.csv — Free"]
    rows = {x["title"]: x for x in fetch(who, "select title, segment_id, source_type from resources")}
    assert rows["survey.csv — Enterprise"]["segment_id"] == campaign.enterprise
    assert rows["survey.csv — Free"]["segment_id"] is None  # no 'Free' segment defined
    assert rows["survey.csv — Enterprise"]["source_type"] == "survey"


def test_another_users_campaign_is_not_found(client, campaign, who):
    who.id = uuid4()  # a different signed-in user
    r = post_file(client, campaign.id, "x.txt", NOTE.encode())
    assert r.status_code == 404 and client.uploads == []


def test_bad_uploads_are_rejected(client, campaign):
    assert post_file(client, campaign.id, "archive.zip", b"PK").status_code == 422
    assert post_file(client, campaign.id, "empty.txt", b"  \n ").status_code == 422
    assert post_file(client, campaign.id, "x.txt", NOTE.encode(), source_type="audio").status_code == 422
    assert client.uploads == []


def test_oversized_upload_is_refused(client, campaign, monkeypatch):
    monkeypatch.setattr(api, "get_settings", lambda: Settings(max_upload_mb=0))
    assert post_file(client, campaign.id, "x.txt", b"hello").status_code == 413


def test_approve_chunks_and_embeds(client, campaign, who, monkeypatch):
    monkeypatch.setattr(api, "embed_texts", lambda texts: [UNIT for _ in texts])
    rid = post_file(client, campaign.id, "long.txt", ("The export is slow. " * 200).encode()).json()["resources"][0]["id"]
    r = client.post(f"/api/v1/resources/{rid}/approve")
    assert r.status_code == 200 and r.json()["chunks"] >= 3
    content = fetch(who, "select content from resources where id = %s", rid)[0]["content"]
    chunks = fetch(who, "select content, start_offset, end_offset, embedding from resource_chunks where resource_id = %s order by chunk_index", rid)
    assert len(chunks) == r.json()["chunks"]
    assert all(c["content"] == content[c["start_offset"] : c["end_offset"]] for c in chunks)
    assert len(chunks[0]["embedding"].to_list()) == 768  # pgvector returns a Vector object
    assert fetch(who, "select status from resources where id = %s", rid)[0]["status"] == "approved"
    assert client.post(f"/api/v1/resources/{rid}/approve").status_code == 409
    listed = client.get("/api/v1/resources", params={"campaign_id": str(campaign.id), "status": "approved"}).json()
    assert listed[0]["chunk_count"] == len(chunks) and "content" not in listed[0]


def test_failed_embedding_leaves_the_resource_staged(client, campaign, who, monkeypatch):
    def boom(_texts):
        raise RuntimeError("quota")

    monkeypatch.setattr(api, "embed_texts", boom)
    rid = post_file(client, campaign.id, "n.txt", NOTE.encode()).json()["resources"][0]["id"]
    assert client.post(f"/api/v1/resources/{rid}/approve").status_code == 502
    assert fetch(who, "select status from resources where id = %s", rid)[0]["status"] == "staged"
    assert fetch(who, "select count(*) as n from resource_chunks")[0]["n"] == 0


def test_other_user_cannot_approve_or_see_a_resource(client, campaign, who):
    rid = post_file(client, campaign.id, "n.txt", NOTE.encode()).json()["resources"][0]["id"]
    who.id = uuid4()
    assert client.post(f"/api/v1/resources/{rid}/approve").status_code == 404
    assert client.get("/api/v1/resources", params={"campaign_id": str(campaign.id)}).json() == []


def test_reject(client, campaign, who):
    rid = post_file(client, campaign.id, "n.txt", NOTE.encode()).json()["resources"][0]["id"]
    assert client.post(f"/api/v1/resources/{rid}/reject").json()["status"] == "rejected"
    assert client.post(f"/api/v1/resources/{rid}/reject").status_code == 404  # no longer staged


def test_research_stages_readable_pages(client, campaign, who, monkeypatch):
    hits = [web.SearchHit("Good page", "https://example.org/a", "s"), web.SearchHit("Dead", "https://example.org/b", "s")]
    monkeypatch.setattr(web, "search_web", lambda q, n: hits)
    page_text = "Users of project tools complain that reporting is slow. Many teams export data by hand. " * 4
    monkeypatch.setattr(web, "fetch_page", lambda url: web.Page("Good page", url, page_text) if url.endswith("/a") else None)
    r = client.post("/api/v1/research", json={"campaign_id": str(campaign.id), "query": "project tool reporting complaints"})
    assert r.status_code == 200, r.text
    ok, dead = r.json()
    assert ok["resource"]["status"] == "staged" and dead["skipped"] == "could not be read"
    row = fetch(who, "select source_type, source_url, summary, status from resources")[0]
    assert row["source_type"] == "web_scrape" and row["source_url"] == "https://example.org/a"
    assert row["summary"].startswith("Users of project tools complain")


def test_research_requires_own_campaign(client, campaign, who):
    who.id = uuid4()
    r = client.post("/api/v1/research", json={"campaign_id": str(campaign.id), "query": "anything at all"})
    assert r.status_code == 404


MALAY_NOTE = (
    "Pertama sekali, kami menguruskan lima belas kedai di pusat beli-belah ini. Setiap hari kami buang "
    "lebih kurang dua puluh kilogram sisa makanan. Okay, jadi kami ada dua tong, satu hijau untuk sisa "
    "makanan dan satu lagi untuk kertas dan plastik. Hubungi ahmad@pusat.com.my untuk soalan lanjut."
)


def test_non_english_text_keeps_its_words_and_returns_a_review_notice(client, campaign, who):
    r = post_file(client, campaign.id, "temuduga.txt", MALAY_NOTE.encode())
    assert r.status_code == 200, r.text
    res = r.json()["resources"][0]
    assert "Names were not scrubbed" in res["pii_notice"] and res["redactions"] == {"EMAIL_ADDRESS": 1}
    row = fetch(who, "select content, pii_note from resources where id = %s", res["id"])[0]
    assert "Pertama sekali" in row["content"] and "Okay" in row["content"] and "<PERSON>" not in row["content"]
    assert "ahmad@pusat.com.my" not in row["content"] and row["pii_note"] == res["pii_notice"]
    listed = client.get("/api/v1/resources", params={"campaign_id": str(campaign.id)}).json()
    assert listed[0]["pii_note"] == res["pii_notice"]


def test_english_text_has_no_review_notice(client, campaign):
    res = post_file(client, campaign.id, "en.txt", NOTE.encode()).json()["resources"][0]
    assert res["pii_notice"] is None
