from src.embedding import embedder, get_conn

THRESHOLD = 0.38


def search(question, limit=3):
    conn = get_conn()
    vec = embedder(question)

    rows = conn.execute(
        "SELECT content, embedding <=> %s AS distance "
        "FROM document_chunks ORDER BY distance LIMIT %s",
        (vec, limit),
    ).fetchall()
    conn.close()

    results = []
    for row in rows:
        results.append((row[0], row[1]))
    return results


def has_answer(results):
    if len(results) == 0:
        return False
    best_distance = results[0][1]
    return best_distance < THRESHOLD


if __name__ == "__main__":
    question = "Do you sell washing machines?"
    results = search(question)

    if has_answer(results):
        for text, distance in results:
            print(round(distance, 3))
            print(text)
            print("---")
    else:
        print("I don't know. Let me connect you to a human agent.")