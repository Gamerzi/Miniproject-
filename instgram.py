import os
from urllib.parse import quote

from playwright.sync_api import sync_playwright
from groq import Groq

PROFILE_DIR = r"C:\Users\sasti\playwright_ig_profile"


def get_groq_client():
    api_key = ""
    if not api_key:
        raise RuntimeError("Set GROQ_API_KEY as an environment variable first.")
    return Groq(api_key=api_key)


def collect_post_urls(page, max_results):
    urls = set()
    attempts = 0

    while len(urls) < max_results and attempts < 8:
        links = page.locator("a[href*='/p/'], a[href*='/reel/']")
        n = links.count()

        for i in range(n):
            href = links.nth(i).get_attribute("href")
            if href:
                full = "https://www.instagram.com" + href.split("?")[0]
                urls.add(full)

        if len(urls) >= max_results:
            break

        page.mouse.wheel(0, 2000)
        page.wait_for_timeout(1500)
        attempts += 1

    return list(urls)[:max_results]


def get_post_info(page, url):
    """Read caption/author from og: meta tags — fast, DOM-layout independent."""
    data = {"url": url}

    page.goto(url, wait_until="domcontentloaded", timeout=15000)
    page.wait_for_timeout(1500)

    try:
        og_desc = page.locator("meta[property='og:description']").get_attribute(
            "content", timeout=5000
        )
    except:
        og_desc = None

    try:
        og_title = page.locator("meta[property='og:title']").get_attribute(
            "content", timeout=5000
        )
    except:
        og_title = None

    # og:title is usually "X likes, Y comments - author on Instagram: ..."
    # og:description often has the actual caption text
    data["caption"] = og_desc if og_desc else "Not Found"

    if og_title and " on Instagram" in og_title:
        data["author"] = og_title.split(" on Instagram")[0].split(" - ")[-1].strip()
    else:
        data["author"] = "Not Found"

    return data


def search_instagram(query, max_results=5):
    collected = []

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=False,
            slow_mo=150,
            viewport={"width": 1280, "height": 800},
        )
        page = context.pages[0] if context.pages else context.new_page()

        page.goto("https://www.instagram.com/")
        page.wait_for_timeout(3000)
        if page.locator("input[name='username']").count() > 0:
            context.close()
            raise RuntimeError("Not logged in. Run ig_setup_login.py first and log in manually.")

        tag = query.replace(" ", "").lower()
        page.goto(f"https://www.instagram.com/explore/tags/{quote(tag)}/")

        try:
            page.wait_for_selector("a[href*='/p/'], a[href*='/reel/']", timeout=10000)
        except:
            print(f"No posts found for #{tag}.")
            context.close()
            return []

        urls = collect_post_urls(page, max_results)
        count = len(urls)

        print("=" * 80)
        print(f"Top {count} Instagram Posts for #{tag}\n")

        for i, url in enumerate(urls):
            print("=" * 80)
            print(f"Post {i+1}: {url}")

            data = get_post_info(page, url)

            print("Author  :", data["author"])
            print("Caption :", data["caption"][:300])
            print()

            collected.append(data)

        context.close()

    return collected


def summarize_post(client, post):
    prompt = (
        f"Author: {post['author']}\n"
        f"Caption: {post['caption'][:1000]}\n\n"
        "Summarize this Instagram post in 1-2 sentences based only on the info above."
    )
    response = client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=[
            {"role": "system", "content": "You are a concise social media summarizer. Use only the given info."},
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content.strip()


def generate_report(client, query, posts):
    context_text = "\n---\n".join(
        f"Author: {p['author']}\nCaption: {p['caption'][:1000]}\nURL: {p['url']}"
        for p in posts
    )
    prompt = f"""
You are a social media research analyst. Based ONLY on the Instagram posts below
for the search "{query}", write a short report covering:

1. Overview of content themes
2. Notable accounts/authors
3. Tone/style patterns
4. Summary table (author, one-line topic)

Context:
{context_text}
"""
    response = client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=[
            {"role": "system", "content": "You are a precise research analyst. Use only the provided context."},
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content.strip()


if __name__ == "__main__":
    query = input("Enter Instagram Search (hashtag, no #) : ")

    posts = search_instagram(query, max_results=5)

    if not posts:
        print("\nNo posts collected — nothing to summarize.")
    else:
        client = get_groq_client()

        print("\n" + "=" * 80)
        print("AI SUMMARIES")
        print("=" * 80)
        for i, p in enumerate(posts, start=1):
            print(f"\nPost {i}: {summarize_post(client, p)}")

        print("\n" + "=" * 80)
        print("RESEARCH REPORT")
        print("=" * 80 + "\n")
        print(generate_report(client, query, posts))