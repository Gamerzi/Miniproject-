from fastapi import FastAPI, Request, HTTPException, File, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from dotenv import load_dotenv
import time
import os
import shutil

# ---------------------------------------------------------------------------
# Load environment variables from .env (must sit next to this file, or set
# the path explicitly: load_dotenv(dotenv_path="/path/to/.env"))
# ---------------------------------------------------------------------------
load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
SERPER_API_KEY = os.getenv("SERPER_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
EXA_API_KEY = os.getenv("EXA_API_KEY")
JINA_API_KEY = os.getenv("JINA_API_KEY")

app = FastAPI(title="AI Research Assistant")

# Mount Static Files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Configure Jinja2 Templates
templates = Jinja2Templates(directory="templates")
templates.env.cache = None


class ResearchRequest(BaseModel):
    platform: str
    query: str
    deep_search: bool = False  # True -> query every provider (DuckDuckGo/Serper/Tavily/Exa)


class ChatRequest(BaseModel):
    query: str
    context: str


@app.get("/reports", response_class=HTMLResponse)
async def list_reports(request: Request):
    """Lists every saved research report (.md file) in the reports/ folder,
    newest first, each linking to /reports/{filename} to view it rendered."""
    reports_dir = "reports"
    os.makedirs(reports_dir, exist_ok=True)

    files = [f for f in os.listdir(reports_dir) if f.lower().endswith(".md")]
    # newest first, based on file modification time
    files.sort(key=lambda f: os.path.getmtime(os.path.join(reports_dir, f)), reverse=True)

    rows = "".join(
        f'<li><a href="/reports/{f}">{f}</a></li>'
        for f in files
    ) or "<li>No reports saved yet.</li>"

    html = f"""
    <html>
    <head>
        <title>Saved Reports</title>
        <style>
            body {{ background:#0f1115; color:#e6e6e6; font-family: Inter, sans-serif; padding: 2rem; }}
            a {{ color:#8ab4f8; text-decoration:none; }}
            a:hover {{ text-decoration:underline; }}
            ul {{ line-height: 2; }}
            h1 {{ font-family: Outfit, sans-serif; }}
        </style>
    </head>
    <body>
        <h1>Saved Research Reports</h1>
        <ul>{rows}</ul>
        <p><a href="/">&larr; Back to Research Assistant</a></p>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.get("/reports/{filename}", response_class=HTMLResponse)
async def view_report(filename: str):
    """Renders a single saved .md report as styled HTML in the browser."""
    import markdown as md_lib

    # Prevent path traversal (e.g. ../../app.py) - only allow plain filenames
    # that live directly inside reports/ and end in .md
    safe_name = os.path.basename(filename)
    if not safe_name.lower().endswith(".md") or safe_name != filename:
        raise HTTPException(status_code=400, detail="Invalid report filename")

    file_path = os.path.join("reports", safe_name)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="Report not found")

    with open(file_path, "r", encoding="utf-8") as f:
        raw_md = f.read()

    body_html = md_lib.markdown(raw_md, extensions=["tables", "fenced_code", "sane_lists"])

    html = f"""
    <html>
    <head>
        <title>{safe_name}</title>
        <style>
            body {{
                background:#0f1115; color:#e6e6e6; font-family: Inter, sans-serif;
                max-width: 860px; margin: 0 auto; padding: 2.5rem 1.5rem; line-height: 1.65;
            }}
            h1, h2, h3 {{ font-family: Outfit, sans-serif; color:#fff; }}
            a {{ color:#8ab4f8; }}
            table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
            th, td {{ border: 1px solid #333; padding: 0.5rem 0.75rem; text-align:left; }}
            th {{ background:#1a1d24; }}
            hr {{ border-color:#2a2d35; }}
            code {{ background:#1a1d24; padding: 0.1rem 0.35rem; border-radius: 4px; }}
            .back-link {{ display:inline-block; margin-bottom: 1.5rem; }}
        </style>
    </head>
    <body>
        <a class="back-link" href="/reports">&larr; All Reports</a>
        {body_html}
    </body>
    </html>
    """
    return HTMLResponse(content=html)


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


def run_deep_search_sync(query_topic: str, deep_search: bool = False):
    """Runs the multi-source research agent and shapes the result the same way the
    other platform handlers do, so the existing frontend can render it unchanged.

    deep_search=False (default): fast mode - fallback chain, stops at the first
        provider that returns results (DuckDuckGo -> Serper -> Tavily -> Exa).
    deep_search=True: queries every configured provider and tags each source
        with which one found it (see ResearchAgent.research in research.py).
    """
    from research import ResearchAgent

    # ResearchAgent is expected to read SERPER_API_KEY / TAVILY_API_KEY /
    # EXA_API_KEY / JINA_API_KEY / GROQ_API_KEY itself via os.getenv(...),
    # since load_dotenv() above already populated the process environment.
    agent = ResearchAgent(llm_model="openai/gpt-oss-20b", max_results=5, output_dir="reports")
    article_markdown, report_path, source_urls, providers_per_source = agent.research(
        query_topic, verbose=True, deep_search=deep_search
    )

    main_source = source_urls[0] if source_urls else (
        f"https://duckduckgo.com/?q={query_topic.replace(' ', '+')}"
    )

    return {
        "title": f"Deep Research: '{query_topic}'",
        "summary": article_markdown,
        "source": main_source,
        "platform": "Deep Search",
        "report_path": report_path,
        "source_urls": source_urls,
        # Consumed by the "Sources by Provider" panel in the frontend -
        # each entry: {"url": ..., "title": ..., "provider": "DuckDuckGo"}
        "sources": providers_per_source,
    }


def run_research_sync(platform_name: str, query_topic: str, deep_search: bool = False):
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

        if not GROQ_API_KEY:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Add it to your .env file "
                "(get a key at https://console.groq.com/keys)."
            )
        client = Groq(api_key=GROQ_API_KEY)
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

    elif platform_name.lower() == "deep search":
        return run_deep_search_sync(query_topic, deep_search=deep_search)

    else:
        raise ValueError("Unsupported platform selected")


def run_chat_sync(query: str, context: str):
    from groq import Groq
    if not GROQ_API_KEY:
        raise RuntimeError(
            "GROQ_API_KEY is not set. Add it to your .env file "
            "(get a key at https://console.groq.com/keys)."
        )
    client = Groq(api_key=GROQ_API_KEY)

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
        result = await run_in_threadpool(run_research_sync, req.platform, req.query, req.deep_search)
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