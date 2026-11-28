# MoroccoTech support bot

![CI](https://github.com/mamineboukal-cyber/AI_Customer_Support/actions/workflows/ci.yml/badge.svg)

RAG customer-support bot for MoroccoTech (Postgres + pgvector retrieval, Gemini generation).

## Admin routes (`/admin/...`): no authentication yet

The admin routes have **no login yet**:

- `POST /admin/upload`: one PDF of up to 10 MB, saved in `data/inbox`, ingested, then
  moved to `data/processed`.
- `GET /admin/stats`: numbers for the dashboard home page (waiting inquiries, and
  today's conversations, handoffs and inquiries, "today" being the Africa/Casablanca
  day), plus the number of documents.
- `GET /admin/documents`: the knowledge-base documents with their chunk counts, most
  recently added or updated first.
- `DELETE /admin/documents/{id}`: deletes a document and its chunks (204, or 404).
  The file in `data/processed` is kept.

Anyone who can reach the server can read these numbers and add or delete documents in
the bot's knowledge base. Until authentication exists, run the API on the loopback
address only:

```
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Do not use `--host 0.0.0.0` or put this app behind a public proxy. If the admin
interface is later served from a different domain, the API will also need a CORS
configuration that allows only that origin.
