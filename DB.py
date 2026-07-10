from langchain_community.document_loaders import PyPDFDirectoryLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
import chromadb
import os

# setting the environment

DATA_PATH = r"data"
CHROMA_PATH = r"chroma_db"

print("Current Working Directory:", os.getcwd())
print("Files inside data folder:", os.listdir(DATA_PATH))

chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)

collection = chroma_client.get_or_create_collection(
    name="business_manual"
)

# loading the document

loader = PyPDFDirectoryLoader(DATA_PATH)

raw_documents = loader.load()

print("\nNumber of raw documents:", len(raw_documents))

if len(raw_documents) == 0:
    print("No documents were loaded!")
    exit()

print("\nFirst document metadata:")
print(raw_documents[0].metadata)

print("\nFirst 500 characters of first document:")
print(raw_documents[0].page_content[:500])

# splitting the document

text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=300,
    chunk_overlap=100,
    length_function=len,
    is_separator_regex=False,
)

chunks = text_splitter.split_documents(raw_documents)

print("\nNumber of chunks:", len(chunks))

if len(chunks) == 0:
    print("No chunks were created!")
    exit()

# preparing to be added in chromadb

documents = []
metadata = []
ids = []

for i, chunk in enumerate(chunks):
    documents.append(chunk.page_content)
    metadata.append(chunk.metadata)
    ids.append(f"ID{i}")

print("\nPrepared data:")
print("Documents:", len(documents))
print("Metadata :", len(metadata))
print("IDs       :", len(ids))

# adding to chromadb

collection.upsert(
    documents=documents,
    metadatas=metadata,
    ids=ids
)

print("\nDatabase created successfully!")