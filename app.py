from fastapi import FastAPI, Request, HTTPException, File, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
import time
import os
import shutil

app = FastAPI(title="AI Research Assistant")

# Mount Static Files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Configure Jinja2 Templates
templates = Jinja2Templates(directory="templates")
templates.env.cache = None

class ResearchRequest(BaseModel):
    platform: str
    query: str

class ChatRequest(BaseModel):
    query: str
    context: str

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")
    try:
        os.makedirs("data", exist_ok=True)
        file_path = os.path.join("data", file.filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        return {"filename": file.filename, "status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def run_db_sync_sync():
    from langchain_community.document_loaders import PyPDFDirectoryLoader
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    import chromadb
    
    logs = []
    logs.append("Sync process started...")
    
    DATA_PATH = r"data"
    CHROMA_PATH = r"chroma_db"
    
    if not os.path.exists(DATA_PATH) or len(os.listdir(DATA_PATH)) == 0:
        logs.append("Error: No documents found in data folder!")
        return {"status": "error", "logs": logs}
        
    logs.append(f"Ingesting documents from '{DATA_PATH}'...")
    try:
        loader = PyPDFDirectoryLoader(DATA_PATH)
        raw_documents = loader.load()
        logs.append(f"Loaded {len(raw_documents)} raw document pages.")
        
        if len(raw_documents) == 0:
            logs.append("Error: Loaded 0 document pages. Ingestion aborted.")
            return {"status": "error", "logs": logs}
            
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=300,
            chunk_overlap=100,
            length_function=len,
            is_separator_regex=False,
        )
        
        chunks = text_splitter.split_documents(raw_documents)
        logs.append(f"Split documents into {len(chunks)} text chunks.")
        
        documents = []
        metadata = []
        ids = []
        
        for i, chunk in enumerate(chunks):
            documents.append(chunk.page_content)
            metadata.append(chunk.metadata)
            ids.append(f"ID{i}")
            
        chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
        collection = chroma_client.get_or_create_collection(name="business_manual")
        
        logs.append("Upserting chunks to ChromaDB collection 'business_manual'...")
        collection.upsert(
            documents=documents,
            metadatas=metadata,
            ids=ids
        )
        
        logs.append("ChromaDB collection successfully updated!")
        logs.append("Database synchronization complete.")
        return {"status": "success", "logs": logs}
        
    except Exception as e:
        import traceback
        error_msg = f"Exception: {str(e)}"
        logs.append(error_msg)
        logs.append(traceback.format_exc())
        return {"status": "error", "logs": logs}


@app.post("/sync-db")
async def sync_database():
    try:
        result = await run_in_threadpool(run_db_sync_sync)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def run_research_sync(platform_name: str, query_topic: str):
    if platform_name.lower() == "youtube":
        import youtube
        videos = youtube.search_youtube(query_topic, max_results=5)
        if not videos:
            return {
                "title": f"YouTube Research: '{query_topic}'",
                "summary": "No videos were found for this query.",
                "source": f"https://www.youtube.com/results?search_query={query_topic.replace(' ', '+')}",
                "platform": "YouTube"
            }
        client = youtube.get_groq_client()
        context = youtube.build_context(videos)
        report = youtube.generate_research_report(client, query_topic, videos, context)
        
        main_source = videos[0]["url"] if videos else f"https://www.youtube.com/results?search_query={query_topic.replace(' ', '+')}"
        return {
            "title": f"YouTube Research: '{query_topic}'",
            "summary": report,
            "source": main_source,
            "platform": "YouTube"
        }
        
    elif platform_name.lower() == "instagram":
        import instgram
        posts = instgram.search_instagram(query_topic, max_results=5)
        if not posts:
            return {
                "title": f"Instagram Research: #{query_topic.replace(' ', '')}",
                "summary": "No posts were found for this hashtag.",
                "source": f"https://www.instagram.com/explore/tags/{query_topic.replace(' ', '')}/",
                "platform": "Instagram"
            }
        client = instgram.get_groq_client()
        report = instgram.generate_report(client, query_topic, posts)
        
        main_source = posts[0]["url"] if posts else f"https://www.instagram.com/explore/tags/{query_topic.replace(' ', '')}/"
        return {
            "title": f"Instagram Research: #{query_topic.replace(' ', '')}",
            "summary": report,
            "source": main_source,
            "platform": "Instagram"
        }
        
    elif platform_name.lower() == "linkedin":
        import linkedIn
        posts = linkedIn.search_linkedin(query_topic, max_results=5)
        if not posts:
            return {
                "title": f"LinkedIn Research: '{query_topic}'",
                "summary": "No posts were found for this keyword.",
                "source": f"https://www.linkedin.com/search/results/content/?keywords={query_topic.replace(' ', '%20')}",
                "platform": "LinkedIn"
            }
        client = linkedIn.get_groq_client()
        report = linkedIn.generate_report(client, query_topic, posts)
        
        main_source = posts[0]["profileUrl"] if posts else f"https://www.linkedin.com/search/results/content/?keywords={query_topic.replace(' ', '%20')}"
        return {
            "title": f"LinkedIn Research: '{query_topic}'",
            "summary": report,
            "source": main_source,
            "platform": "LinkedIn"
        }
        
    elif platform_name.lower() == "pdf documents":
        import chromadb
        from groq import Groq
        
        CHROMA_PATH = r"chroma_db"
        chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
        collection = chroma_client.get_or_create_collection(name="business_manual")
        
        results = collection.query(
            query_texts=[query_topic],
            n_results=6
        )
        
        context_docs = results["documents"]
        
        client = Groq(api_key="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")
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
{context_docs}
"""
        response = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query_topic}
            ]
        )
        answer = response.choices[0].message.content.strip()
        
        main_source = "data/svl.pdf"
        if results.get("metadatas") and len(results["metadatas"]) > 0 and len(results["metadatas"][0]) > 0:
            source_meta = results["metadatas"][0][0].get("source")
            if source_meta:
                main_source = source_meta
                
        return {
            "title": f"Document Query: '{query_topic}'",
            "summary": answer,
            "source": main_source,
            "platform": "PDF Documents"
        }
    else:
        raise ValueError("Unsupported platform selected")


def run_chat_sync(query: str, context: str):
    from groq import Groq
    client = Groq(api_key="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")
    
    system_prompt = f"""
You are a research assistant. Answer the user's follow-up question based on the research context provided below.
Be helpful, precise, and professional.

-----------------------
Context:
{context}
"""
    response = client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query}
        ]
    )
    return response.choices[0].message.content.strip()


@app.post("/research")
async def do_research(req: ResearchRequest):
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    
    try:
        result = await run_in_threadpool(run_research_sync, req.platform, req.query)
        return result
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat")
async def do_chat(req: ChatRequest):
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    
    try:
        answer = await run_in_threadpool(run_chat_sync, req.query, req.context)
        return {"response": answer}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
