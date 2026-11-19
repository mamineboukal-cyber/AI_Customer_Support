import os
import psycopg
from dotenv import load_dotenv

load_dotenv()

FILES = [
    ("data/knowledge_base/FAQ.md", "Frequently Asked Questions", "faq"),
    ("data/knowledge_base/shipping.md", "Shipping Policy", "shipping"),
    ("data/knowledge_base/payments.md", "Payment Policy", "payment"),
    ("data/knowledge_base/products.md", "Products", "products"),
    ("data/knowledge_base/returns.md", "Returns Policy", "returns"),
    ("data/knowledge_base/warranty.md", "Warranty Policy", "warranty"),
]

conn = psycopg.connect(
    dbname=os.getenv("DATABASE_NAME"),
    user=os.getenv("DATABASE_USER"),
    password=os.getenv("DATABASE_PASSWORD"),
    host=os.getenv("DATABASE_HOST"),
    port=int(os.getenv("DATABASE_PORT")),
)

with conn:
    cur = conn.cursor()
    cur.execute("DELETE FROM document_chunks")
    cur.execute("DELETE FROM documents")
    for path, title, category in FILES:
        content = open(path, encoding="utf-8").read().strip()
        cur.execute(
            "INSERT INTO documents (title, category, content) VALUES (%s, %s, %s)",
            (title, category, content),
        )
        print("loaded:", title)

conn.close()
