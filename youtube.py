import os
import re
from urllib.parse import quote

from playwright.sync_api import sync_playwright
from groq import Groq
from dotenv import load_dotenv

# Load environment variables from .env (must be in the same folder as this
# script, or the project root if you run this via app.py)
load_dotenv()


# =========================================================
# YOUTUBE SCRAPER
# =========================================================

def get_video_info(page):
    """Extract info assuming we're already on the video page."""
    page.wait_for_selector("h1.ytd-watch-metadata yt-formatted-string", timeout=10000)

    data = {}

    try:
        data["title"] = page.locator(
            "h1.ytd-watch-metadata yt-formatted-string"
        ).first.inner_text()
    except:
        data["title"] = "Not Found"

    try:
        data["channel"] = page.locator("#owner #channel-name a").first.inner_text()
    except:
        data["channel"] = "Not Found"

    try:
        info_text = page.locator("#info-container, #above-the-fold #info").first.inner_text()
        match = re.search(r"[\d,\.]+[KMB]?\s*views", info_text)
        data["views"] = match.group(0) if match else "Not Found"
    except:
        data["views"] = "Not Found"

    try:
        page.evaluate(
            """() => {
                const btn = document.querySelector(
                    'ytd-text-inline-expander#description-inline-expander tp-yt-paper-button#expand'
                );
                if (btn) btn.click();
            }"""
        )
        page.wait_for_timeout(300)
    except:
        pass

    try:
        data["description"] = page.locator("#description-inline-expander").inner_text()
    except:
        try:
            data["description"] = page.locator("#description").inner_text()
        except:
            data["description"] = "Not Found"

    return data


def search_youtube(query, max_results=5):
    """Scrapes top N video results and returns a list of dicts."""
    collected = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=150)
        page = browser.new_page(viewport={"width": 1280, "height": 800})

        search_url = f"https://www.youtube.com/results?search_query={quote(query)}"
        page.goto(search_url)
        page.wait_for_selector("ytd-video-renderer", timeout=10000)

        videos = page.locator("ytd-video-renderer")
        count = min(videos.count(), max_results)

        print("=" * 80)
        print(f"Top {count} Results\n")

        for i in range(count):
            title = videos.nth(i).locator("#video-title").inner_text()
            print(f"{i+1}. {title}")

        print("\n" + "=" * 80)
        print("Collecting Video Information...\n")

        for i in range(count):
            print("=" * 80)
            print(f"Video {i+1}")

            videos = page.locator("ytd-video-renderer")
            video = videos.nth(i)
            video_title_locator = video.locator("#video-title")

            url = "https://www.youtube.com" + video_title_locator.get_attribute("href")

            video_title_locator.scroll_into_view_if_needed()
            video_title_locator.click()
            page.wait_for_url("**/watch?v=**", timeout=10000)

            info = get_video_info(page)
            info["url"] = url

            print("Title      :", info["title"])
            print("Channel    :", info["channel"])
            print("Views      :", info["views"])
            print("URL        :", url)
            print()

            collected.append(info)

            page.go_back()
            page.wait_for_selector("ytd-video-renderer", timeout=10000)

        browser.close()

    return collected


# =========================================================
# GROQ AI SUMMARY + RESEARCH REPORT
# =========================================================

def build_context(videos):
    """Formats scraped video data into a single text block for the LLM."""
    blocks = []
    for i, v in enumerate(videos, start=1):
        blocks.append(
            f"Video {i}\n"
            f"Title: {v['title']}\n"
            f"Channel: {v['channel']}\n"
            f"Views: {v['views']}\n"
            f"URL: {v['url']}\n"
            f"Description: {v['description'][:1500]}\n"
        )
    return "\n---\n".join(blocks)


def get_groq_client():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY environment variable not set. "
            "Add it to your .env file, e.g.:\n"
            "  GROQ_API_KEY=your_key_here"
        )
    return Groq(api_key=api_key)


def summarize_video(client, video):
    """Generates a short summary for a single video."""
    prompt = (
        f"Title: {video['title']}\n"
        f"Channel: {video['channel']}\n"
        f"Views: {video['views']}\n"
        f"Description: {video['description'][:1500]}\n\n"
        "Summarize this video in 2-3 sentences based only on the info above."
    )

    response = client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=[
            {"role": "system", "content": "You are a concise video summarizer. Use only the given info."},
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content.strip()


def generate_research_report(client, query, videos, context):
    """Generates a combined research-style report across all videos."""
    prompt = f"""
You are a research analyst. Based ONLY on the search results below for the
query "{query}", write a research report with these sections:

1. Overview — what kind of content dominates these search results
2. Key Themes — recurring topics/angles across the videos
3. Notable Channels — which channels appear and what they focus on
4. Audience Signal — what the view counts suggest about popularity
5. Summary Table — one line per video (title, channel, views)

Context:
{context}
"""

    response = client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=[
            {"role": "system", "content": "You are a precise research analyst. Use only the provided context, do not invent facts."},
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content.strip()


# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":
    query = input("Enter Search Query : ")

    videos = search_youtube(query, max_results=5)
    client = get_groq_client()
    context = build_context(videos)

    print("\n" + "=" * 80)
    print("AI SUMMARIES")
    print("=" * 80)

    for i, v in enumerate(videos, start=1):
        summary = summarize_video(client, v)
        print(f"\nVideo {i}: {v['title']}")
        print(f"Summary: {summary}")

    print("\n" + "=" * 80)
    print("RESEARCH REPORT")
    print("=" * 80 + "\n")

    report = generate_research_report(client, query, videos, context)
    print(report)