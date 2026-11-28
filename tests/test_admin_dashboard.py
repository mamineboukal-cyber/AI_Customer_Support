"""GET /admin/stats, GET /admin/documents, DELETE /admin/documents/{id} against the
throwaway test DB (conftest.py). No Gemini call anywhere."""
import hashlib
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from fastapi.testclient import TestClient

import app.ingestion.upload as upload
from app.admin_data import DASHBOARD_TIME_ZONE, stats
from app.main import app

client = TestClient(app)
UTC = timezone.utc


def at(text):
    """'2026-07-15 12:00' -> an aware UTC datetime."""
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


# ---------------------------------------------------------------- data helpers

def conversation(db):
    return db.execute("INSERT INTO conversations DEFAULT VALUES RETURNING id").fetchone()[0]


def message(db, conversation_id, created_at, role="assistant", kind="normal"):
    db.execute(
        "INSERT INTO messages (conversation_id, role, content, reply_kind, created_at) "
        "VALUES (%s, %s, 'x', %s, %s)",
        (conversation_id, role, kind if role == "assistant" else None, created_at),
    )


def inquiry(db, status, topic):
    ledger = db.execute(
        "INSERT INTO unanswered_questions (question, normalized_question) VALUES (%s, %s) "
        "RETURNING id",
        (topic, topic),
    ).fetchone()[0]
    answered = status != "waiting"
    db.execute(
        "INSERT INTO admin_inquiries (unanswered_question_id, conversation_id, status, "
        "admin_answer, answered_at, delivered_at) VALUES (%s, %s, %s, %s, %s, %s)",
        (
            ledger, conversation(db), status,
            "answer" if answered else None,
            datetime.now(UTC) if answered else None,
            datetime.now(UTC) if status == "delivered" else None,
        ),
    )


def document(db, name, chunks=0, updated_at=None, category="general"):
    doc_id = db.execute(
        "INSERT INTO documents (title, category, content, source_name, content_hash, "
        "created_at, updated_at) VALUES (%s, %s, 'text', %s, %s, "
        "coalesce(%s, now()), coalesce(%s, now())) RETURNING id",
        (name.title(), category, name, hashlib.sha256(name.encode()).hexdigest(),
         updated_at, updated_at),
    ).fetchone()[0]
    for i in range(chunks):
        db.execute(
            "INSERT INTO document_chunks (document_id, content, chunk_index) VALUES (%s, %s, %s)",
            (doc_id, f"{name} chunk {i}", i),
        )
    return doc_id


def count(db, table):
    return db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def snapshot(db):
    """Everything a document delete must not touch, plus the documents themselves."""
    tables = ("visitors", "conversations", "messages", "admin_inquiries", "unanswered_questions")
    return {t: count(db, t) for t in tables}


ZERO = {
    "waiting_inquiries": 0,
    "conversations_today": 0,
    "handoffs_today": 0,
    "inquiries_today": 0,
    "documents": 0,
}


def numbers(result):
    return {k: v for k, v in result.items() if k in ZERO}


# ---------------------------------------------------------------- stats

def test_time_zone_is_casablanca():
    assert DASHBOARD_TIME_ZONE == "Africa/Casablanca"


def test_stats_on_an_empty_database(memory_db):
    response = client.get("/admin/stats")

    assert response.status_code == 200
    body = response.json()
    assert numbers(body) == ZERO
    assert body["time_zone"] == "Africa/Casablanca"
    datetime.strptime(body["day"], "%Y-%m-%d")


def test_each_stat_with_known_data(memory_db):
    db = memory_db
    now = at("2026-07-15 12:00")  # 13:00 in Casablanca (UTC+1 in July)
    today, yesterday = at("2026-07-15 10:00"), at("2026-07-14 10:00")

    a = conversation(db)  # today: a normal exchange
    message(db, a, today, role="user")
    message(db, a, today, kind="normal")
    b = conversation(db)  # today: two handoffs, one inquiry, error not counted
    for kind in ("handoff", "handoff", "inquiry", "error"):
        message(db, b, today, kind=kind)
    c = conversation(db)  # only yesterday: not counted at all
    message(db, c, yesterday, role="user")
    message(db, c, yesterday, kind="handoff")
    message(db, c, yesterday, kind="inquiry")
    conversation(db)  # no messages at all
    for status, topic in [("waiting", "t1"), ("waiting", "t2"), ("answered", "t3"), ("delivered", "t4")]:
        inquiry(db, status, topic)
    for name in ("faq", "shipping", "warranty"):
        document(db, name)

    result = stats(now)

    assert result["day"] == "2026-07-15"
    assert numbers(result) == {
        "waiting_inquiries": 2,
        "conversations_today": 2,
        "handoffs_today": 2,
        "inquiries_today": 1,
        "documents": 3,
    }


def test_a_conversation_with_only_a_user_message_today_counts(memory_db):
    message(memory_db, conversation(memory_db), at("2026-07-15 09:00"), role="user")

    assert stats(at("2026-07-15 12:00"))["conversations_today"] == 1


# July: Casablanca is UTC+1, so the local day 2026-07-15 is
# [2026-07-14 23:00 UTC, 2026-07-15 23:00 UTC).
@pytest.mark.parametrize(
    "created_at, counted",
    [
        ("2026-07-14 22:30", False),            # 23:30 local on the 14th
        ("2026-07-14 22:59:59.999999", False),  # last instant of the 14th
        ("2026-07-14 23:00", True),             # local midnight: first instant of the 15th
        ("2026-07-14 23:30", True),             # UTC says the 14th, Casablanca the 15th
        ("2026-07-15 00:30", True),             # UTC says the 15th too
        ("2026-07-15 22:59:59.999999", True),   # last instant of the 15th
        ("2026-07-15 23:00", False),            # local midnight of the 16th
        ("2026-07-15 23:30", False),            # UTC says the 15th, Casablanca the 16th
    ],
)
def test_casablanca_day_boundaries(memory_db, created_at, counted):
    message(memory_db, conversation(memory_db), at(created_at), kind="handoff")

    result = stats(at("2026-07-15 12:00"))

    assert result["handoffs_today"] == int(counted)
    assert result["conversations_today"] == int(counted)


def test_23_30_and_00_30_utc_are_the_same_casablanca_day(memory_db):
    message(memory_db, conversation(memory_db), at("2026-07-14 23:30"), kind="inquiry")
    message(memory_db, conversation(memory_db), at("2026-07-15 00:30"), kind="inquiry")

    # Whichever of the two moments "now" is, it is the 15th in Casablanca.
    for now in ("2026-07-14 23:30", "2026-07-15 00:30"):
        result = stats(at(now))
        assert (result["day"], result["inquiries_today"]) == ("2026-07-15", 2)
    # An hour earlier it is still the 14th there: neither message is "today".
    result = stats(at("2026-07-14 22:30"))
    assert (result["day"], result["inquiries_today"]) == ("2026-07-14", 0)


def test_during_ramadan_casablanca_is_utc(memory_db):
    # Morocco sets its clocks back to UTC+0 during Ramadan (1 March 2026 is inside it).
    message(memory_db, conversation(memory_db), at("2026-02-28 23:30"), kind="handoff")
    message(memory_db, conversation(memory_db), at("2026-03-01 00:30"), kind="handoff")

    result = stats(at("2026-03-01 12:00"))

    assert (result["day"], result["handoffs_today"]) == ("2026-03-01", 1)


def test_day_of_a_clock_change_has_23_hours(memory_db):
    # 22 March 2026: back to UTC+1 after Ramadan, so that local day ends at 23:00 UTC.
    message(memory_db, conversation(memory_db), at("2026-03-22 00:00"), kind="handoff")
    message(memory_db, conversation(memory_db), at("2026-03-22 22:59"), kind="handoff")
    message(memory_db, conversation(memory_db), at("2026-03-22 23:00"), kind="handoff")

    assert stats(at("2026-03-22 12:00"))["handoffs_today"] == 2


def test_stats_route_uses_the_current_day(memory_db):
    c = conversation(memory_db)
    message(memory_db, c, datetime.now(UTC), role="user")
    message(memory_db, c, datetime.now(UTC), kind="handoff")
    message(memory_db, c, datetime.now(UTC) - timedelta(days=2), kind="inquiry")
    inquiry(memory_db, "waiting", "loyalty program")
    document(memory_db, "faq")

    body = client.get("/admin/stats").json()

    # conversations_today: c, not the inquiry's conversation (it has no messages)
    assert numbers(body) == {
        "waiting_inquiries": 1,
        "conversations_today": 1,
        "handoffs_today": 1,
        "inquiries_today": 0,
        "documents": 1,
    }


# ---------------------------------------------------------------- documents list

def test_documents_list_is_empty(memory_db):
    response = client.get("/admin/documents")

    assert response.status_code == 200
    assert response.json() == {"documents": []}


def test_documents_newest_first_with_chunk_counts(memory_db):
    old = document(memory_db, "faq", chunks=3, updated_at=at("2026-07-01 10:00"))
    newest = document(memory_db, "shipping", chunks=5, updated_at=at("2026-07-10 10:00"), category="shipping")
    empty = document(memory_db, "returns", chunks=0, updated_at=at("2026-07-05 10:00"))
    # Same time as `newest`: the higher id (added later) comes first.
    tie = document(memory_db, "warranty", chunks=1, updated_at=at("2026-07-10 10:00"))

    docs = client.get("/admin/documents").json()["documents"]

    assert [(d["id"], d["name"], d["chunks"]) for d in docs] == [
        (tie, "warranty", 1),
        (newest, "shipping", 5),
        (empty, "returns", 0),
        (old, "faq", 3),
    ]
    first = docs[1]
    assert (first["title"], first["category"]) == ("Shipping", "shipping")
    assert datetime.fromisoformat(first["updated_at"]) == at("2026-07-10 10:00")
    assert datetime.fromisoformat(first["created_at"]) == at("2026-07-10 10:00")


def test_updating_a_document_moves_it_to_the_top(memory_db):
    first = document(memory_db, "faq", updated_at=at("2026-07-01 10:00"))
    document(memory_db, "shipping", updated_at=at("2026-07-10 10:00"))

    # The trigger from 0001 sets updated_at = now() on every UPDATE (re-ingestion).
    memory_db.execute("UPDATE documents SET content = 'new' WHERE id = %s", (first,))

    assert client.get("/admin/documents").json()["documents"][0]["id"] == first


# ---------------------------------------------------------------- delete

def test_delete_removes_the_document_and_its_chunks_only(memory_db):
    db = memory_db
    gone = document(db, "faq", chunks=4)
    kept = document(db, "shipping", chunks=2)
    c = conversation(db)
    message(db, c, datetime.now(UTC), role="user")
    message(db, c, datetime.now(UTC), kind="handoff")
    inquiry(db, "waiting", "loyalty program")
    before = snapshot(db)
    kept_chunks = db.execute(
        "SELECT id, content FROM document_chunks WHERE document_id = %s ORDER BY id", (kept,)
    ).fetchall()

    response = client.delete(f"/admin/documents/{gone}")

    assert response.status_code == 204
    assert response.content == b""
    assert db.execute("SELECT id FROM documents").fetchall() == [(kept,)]
    assert db.execute(
        "SELECT count(*) FROM document_chunks WHERE document_id = %s", (gone,)
    ).fetchone() == (0,)
    assert db.execute(
        "SELECT id, content FROM document_chunks ORDER BY id"
    ).fetchall() == kept_chunks
    assert snapshot(db) == before


@pytest.mark.parametrize("bad_id", ["999", "0", "abc", "-1", "1.5", "99999999999", "１"])
def test_delete_unknown_id_is_404_and_changes_nothing(memory_db, bad_id):
    document(memory_db, "faq", chunks=2)

    response = client.delete(f"/admin/documents/{bad_id}")

    assert response.status_code == 404
    assert response.json() == {"detail": f"document {bad_id} not found"}
    assert (count(memory_db, "documents"), count(memory_db, "document_chunks")) == (1, 2)


def test_delete_twice_is_404_the_second_time(memory_db):
    doc_id = document(memory_db, "faq", chunks=1)

    assert client.delete(f"/admin/documents/{doc_id}").status_code == 204
    assert client.delete(f"/admin/documents/{doc_id}").status_code == 404


@pytest.fixture
def refuse_document_delete(memory_db):
    """A trigger that makes deleting any document fail, AFTER its chunks are deleted."""
    memory_db.execute(
        "CREATE FUNCTION test_refuse_delete() RETURNS trigger LANGUAGE plpgsql AS "
        "$$ BEGIN RAISE EXCEPTION 'refused by test'; END; $$"
    )
    memory_db.execute(
        "CREATE TRIGGER test_refuse_delete BEFORE DELETE ON documents "
        "FOR EACH ROW EXECUTE FUNCTION test_refuse_delete()"
    )
    yield
    memory_db.execute("DROP TRIGGER test_refuse_delete ON documents")
    memory_db.execute("DROP FUNCTION test_refuse_delete()")


def test_failed_delete_rolls_back_the_chunks_too(memory_db, refuse_document_delete):
    doc_id = document(memory_db, "faq", chunks=3)

    response = client.delete(f"/admin/documents/{doc_id}")

    assert response.status_code == 500
    assert response.json()["detail"].startswith("could not delete the document: RaiseException: refused by test")
    assert (count(memory_db, "documents"), count(memory_db, "document_chunks")) == (1, 3)


def test_upload_after_delete_is_a_new_document_and_processed_file_is_kept(
    memory_db, tmp_path, monkeypatch, make_pdf
):
    inbox = tmp_path / "data" / "inbox"
    processed = tmp_path / "data" / "processed"
    inbox.mkdir(parents=True)
    monkeypatch.setattr(upload, "INBOX", inbox)
    monkeypatch.setattr(upload, "PROCESSED", processed)
    pdf = make_pdf(tmp_path / "src.pdf", [["Wireless Headphones X1", "Price: 499 MAD"]]).read_bytes()

    def send():
        return client.post("/admin/upload", files={"file": ("Guide.pdf", pdf, "application/pdf")})

    first = send().json()
    assert first["status"] == "created"
    [listed] = client.get("/admin/documents").json()["documents"]
    assert (listed["name"], listed["chunks"]) == ("guide", first["chunks"])

    assert client.delete(f"/admin/documents/{listed['id']}").status_code == 204
    assert client.get("/admin/documents").json() == {"documents": []}
    assert (processed / "Guide.pdf").read_bytes() == pdf  # the processed file stays

    # Same bytes again: without the row it is "created", not "skipped".
    again = send().json()
    assert again["status"] == "created"
    [relisted] = client.get("/admin/documents").json()["documents"]
    assert relisted["id"] != listed["id"]
    assert relisted["chunks"] == again["chunks"] > 0
    assert [p.name for p in processed.iterdir()] == ["Guide.pdf"]
