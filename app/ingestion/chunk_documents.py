from langchain_text_splitters import RecursiveCharacterTextSplitter

CHUNK_SIZE = 250
CHUNK_OVERLAP = 40

splitter = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP,
    length_function=len,
)


def split_text(text):
    return splitter.split_text(text)
