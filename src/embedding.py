import psycopg
from pgvector.psycopg import register_vector
from sentence_transformers import SentenceTransformer
import os
from dotenv import load_dotenv

load_dotenv()

model = SentenceTransformer("BAAI/bge-small-en-v1.5")


def embedder(text):
    return model.encode(text, normalize_embeddings=True)


def get_conn():
    conn = psycopg.connect(
        dbname=os.getenv("DATABASE_NAME"),
        user=os.getenv("DATABASE_USER"),
        password=os.getenv("DATABASE_PASSWORD"),
        host=os.getenv("DATABASE_HOST"),
        port=int(os.getenv("DATABASE_PORT")),
    )
    register_vector(conn)
    return conn


def embed_chunks():
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, content FROM document_chunks WHERE embedding IS NULL"
    ).fetchall()

    for chunk_id, content in rows:
        vec = embedder(content)
        conn.execute(
            "UPDATE document_chunks SET embedding = %s WHERE id = %s",
            (vec, chunk_id),
        )

    conn.commit()
    conn.close()
    print(f"Embedded {len(rows)} chunks")


if __name__ == "__main__":
    embed_chunks()