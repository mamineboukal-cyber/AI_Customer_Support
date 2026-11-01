
from langchain_text_splitters import RecursiveCharacterTextSplitter

text = """
Shipping Policy

Delivery times depend on the destination city.
Casablanca: 1-2 business days.
Rabat: 1-2 business days.
Tangier: 2-3 business days.
Other cities: 2-5 business days.

Shipping is free for orders over 500 MAD.
Orders below this amount may incur a shipping fee.
"""

splitter = RecursiveCharacterTextSplitter(
    chunk_size=250,
    chunk_overlap=40,
    length_function=len,
)

chunks = splitter.split_text(text)

for index, chunk in enumerate(chunks):
    print(f"\n--- Chunk {index} ---")
    print(chunk)
    print(f"Length: {len(chunk)} characters")

