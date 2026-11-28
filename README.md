# MoroccoTech support bot

![CI](https://github.com/mamineboukal-cyber/AI_Customer_Support/actions/workflows/ci.yml/badge.svg)

RAG customer-support bot for MoroccoTech (Postgres + pgvector retrieval, Gemini generation).

## Admin routes (`/admin/...`): no authentication yet

The admin routes, such as `POST /admin/upload` (one PDF of up to 10 MB, saved in
`data/inbox` and ingested), have **no login yet**. Anyone who can reach the server can
upload documents into the bot's knowledge base. Until authentication exists, run the
API on the loopback address only:

```
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Do not use `--host 0.0.0.0` or put this app behind a public proxy. If the admin
interface is later served from a different domain, the API will also need a CORS
configuration that allows only that origin.
