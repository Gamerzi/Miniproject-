import chromadb
from groq import Groq

# Paths
DATA_PATH = r"data"
CHROMA_PATH = r"chroma_db"

# Load ChromaDB
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)

collection = chroma_client.get_or_create_collection(
    name="business_manual"
)

# User Query
user_query = input("Ask a question about the company:\n\n")

# Retrieve relevant chunks
results = collection.query(
    query_texts=[user_query],
    n_results=6
)

print("\nRetrieved Context:\n")
print(results["documents"])

# Groq Client
client = Groq(
    api_key="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"
)

# System Prompt
system_prompt = f"""
You are a helpful AI assistant.

You answer questions ONLY using the information provided in the context below.

Rules:
1. Use only the provided context.
2. Do not use your own knowledge.
3. If the answer is not found in the context, reply exactly:
   I don't know.
4. Give clear and concise answers.

-----------------------
Context:
{results["documents"]}
"""

# Generate Response
response = client.chat.completions.create(
    model="openai/gpt-oss-20b",
    messages=[
        {
            "role": "system",
            "content": system_prompt
        },
        {
            "role": "user",
            "content": user_query
        }
    ]
)

print("\n-----------------------------\n")
print("Answer:\n")
print(response.choices[0].message.content)