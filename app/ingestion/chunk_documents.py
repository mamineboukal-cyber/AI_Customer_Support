from langchain_text_splitters import RecursiveCharacterTextSplitter
import psycopg
import os
from dotenv import load_dotenv

load_dotenv()

conn = psycopg.connect(
    dbname=os.getenv("DATABASE_NAME"),
    user=os.getenv("DATABASE_USER"),
    password=os.getenv("DATABASE_PASSWORD"),
    host=os.getenv("DATABASE_HOST"),
    port=int(os.getenv("DATABASE_PORT")),
)
cur = conn.cursor()
cur.execute("""
SELECT id, title, content
FROM documents """)

documents = cur.fetchall()

splitter = RecursiveCharacterTextSplitter(
    chunk_size=250,
    chunk_overlap=40,
    length_function=len,
)

cur.execute("DELETE FROM document_chunks")

for document_id, title, content in documents:
    chunks = splitter.split_text(content)

    for index, chunk in enumerate(chunks):
        cur.execute(
            """
            INSERT INTO document_chunks (document_id, content, chunk_index)
            VALUES (%s, %s, %s)
            """, (document_id, chunk, index),)

conn.commit()
cur.close()
conn.close()