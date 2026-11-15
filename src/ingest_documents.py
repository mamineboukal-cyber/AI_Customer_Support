import os
import psycopg
from dotenv import load_dotenv

load_dotenv()

FILES = [
    ("Data/FAQ.md", "Frequently Asked Questions", "faq"),
    ("Data/Shipping.md", "Shipping Policy", "shipping"),
    ("Data/payments.md", "Payment Policy", "payment"),
    ("Data/products.md", "Products", "products"),
    ("Data/returns.md", "Returns Policy", "returns"),
    ("Data/warranty.md", "Warranty Policy", "warranty"),
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
