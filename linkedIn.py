import os
from urllib.parse import quote

from playwright.sync_api import sync_playwright
from groq import Groq

PROFILE_DIR = r"C:\Users\sasti\playwright_li_profile"


def get_groq_client():
    api_key = "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"
    if not api_key:
        raise RuntimeError("Set GROQ_API_KEY as an environment variable first.")
    return Groq(api_key=api_key)


# LinkedIn hashes/regenerates its CSS class names (e.g. "_3bc30ca8") on every
# build, so class-based selectors break constantly. Instead we extract posts
# using stable structural/accessibility text: every post's hidden a11y label
# starts with "Feed post", followed by author -> timestamp -> Follow -> body.
EXTRACT_POSTS_JS = """
() => {
    const all = document.querySelectorAll('div');
    const seen = new Set();
    const posts = [];

    for (const el of all) {
        const text = el.innerText || '';
        if (!text.startsWith('Feed post')) continue;

        const authorLink = el.querySelector("a[href*='/in/'], a[href*='/company/']");
        if (!authorLink) continue;
        if (text.length < 100 || text.length > 8000) continue;

        const lines = text.split('\\n').map(l => l.trim()).filter(Boolean);
        const authorLine = lines.length > 1 ? lines[1] : 'Not Found';

        const followIdx = lines.findIndex(
            l => l === 'Follow' || l === '+ Follow' || l === 'Following'
        );
        let bodyLines = followIdx >= 0 ? lines.slice(followIdx + 1) : lines.slice(3);

        const footerMarkers = [
            'Like', 'Comment', 'Repost', 'Send', 'reactions',
            'Activate to view'
        ];
        const bodyEndIdx = bodyLines.findIndex(
            l => footerMarkers.some(m => l.includes(m))
        );
        const body = bodyEndIdx >= 0 ? bodyLines.slice(0, bodyEndIdx) : bodyLines.slice(0, 8);
        const captionText = body.join(' ').trim();

        // Dedupe: nested wrapper divs around the same post produce near-identical
        // text, so we key on author + first 60 chars of caption and keep the first hit.
        const sig = authorLine + '|' + captionText.slice(0, 60);
        if (seen.has(sig)) continue;
        seen.add(sig);

        const href = authorLink.getAttribute('href') || '';
        const profileUrl = href.startsWith('http') ? href : ('https://www.linkedin.com' + href);

        posts.push({
            author: authorLine,
            text: captionText.slice(0, 4000),
            profileUrl: profileUrl
        });
    }

    return posts;
}
"""


EXPAND_CAPTIONS_JS = """
() => {
    // Confirmed from live debugging: LinkedIn's actual caption toggle is a
    // <span> with no class and the exact text "more" (not "...more" or
    // "see more" as commonly assumed). We restrict the plain-"more" match
    // to <span> tags specifically, since <a>/<p> elements with "more" in
    // their text turned out to be unrelated (a "Learn more" link, a nav
    // "More" menu item) — matching those broadly caused false positives.
    const all = document.querySelectorAll('*');
    let clicked = 0;

    const normalize = (s) => s
        .replace(/\\u2026/g, '...')   // normalize real ellipsis char to three dots
        .replace(/\\s+/g, ' ')
        .trim()
        .toLowerCase();

    const phraseTargets = new Set(['...more', 'see more', '...see more']);

    for (const el of all) {
        if (el.children.length > 0) continue;  // only leaf nodes
        const raw = el.innerText || el.textContent || '';
        const t = normalize(raw);

        const isPlainMoreSpan = (el.tagName === 'SPAN' && t === 'more');
        const isPhraseMatch = phraseTargets.has(t);

        if (isPlainMoreSpan || isPhraseMatch) {
            el.click();
            clicked++;
        }
    }
    return clicked;
}
"""


DEBUG_FIND_MORE_JS = """
() => {
    const all = document.querySelectorAll('*');
    const hits = [];
    for (const el of all) {
        if (el.children.length > 0) continue;
        const raw = (el.innerText || el.textContent || '').trim();
        if (raw.length > 0 && raw.length < 20 && raw.toLowerCase().includes('more')) {
            hits.push({
                tag: el.tagName,
                text: raw,
                classes: el.className
            });
        }
        if (hits.length >= 15) break;
    }
    return hits;
}
"""


def expand_all_captions(page):
    """Click every '...more' toggle on the page so full captions render in the DOM."""
    total_clicked = 0
    # Run a couple of passes since clicking can reveal more nested "...more" buttons
    for _ in range(4):
        clicked = page.evaluate(EXPAND_CAPTIONS_JS)
        total_clicked += clicked
        if clicked == 0:
            break
        page.wait_for_timeout(600)
    print(f"[debug] '...more' toggles clicked this pass: {total_clicked}")

    if total_clicked == 0:
        hits = page.evaluate(DEBUG_FIND_MORE_JS)
        if hits:
            print("[debug] No toggle matched. Leaf elements containing 'more' found on page:")
            for h in hits:
                print(f"    <{h['tag']} class=\"{h['classes']}\"> -> \"{h['text']}\"")

    return total_clicked


def extract_posts_from_page(page, max_results):
    """Scroll until enough unique posts are found, expanding captions each pass,
    then extract via JS landmark parsing on the fully-expanded DOM."""
    attempts = 0
    posts = []

    while attempts < 10:
        expand_all_captions(page)
        posts = page.evaluate(EXTRACT_POSTS_JS)
        if len(posts) >= max_results:
            break
        page.mouse.wheel(0, 2500)
        page.wait_for_timeout(1500)
        attempts += 1

    # Final expand + re-extract pass in case new posts loaded on the last scroll
    expand_all_captions(page)
    posts = page.evaluate(EXTRACT_POSTS_JS)

    return posts[:max_results]


def search_linkedin(query, max_results=5):
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=False,
            slow_mo=150,
            viewport={"width": 1280, "height": 800},
        )
        page = context.pages[0] if context.pages else context.new_page()

        page.goto("https://www.linkedin.com/feed/", timeout=15000)
        page.wait_for_timeout(3000)

        if page.locator("#username").count() > 0:
            context.close()
            raise RuntimeError("Not logged in. Run li_setup_login.py first and log in manually.")

        search_url = f"https://www.linkedin.com/search/results/content/?keywords={quote(query)}"
        page.goto(search_url, timeout=15000)
        page.wait_for_timeout(4000)

        try:
            page.wait_for_function(
                "document.body.innerText.includes('Feed post')", timeout=10000
            )
        except Exception:
            print(f"No posts found for '{query}'.")
            context.close()
            return []

        posts = extract_posts_from_page(page, max_results)
        count = len(posts)

        print("=" * 80)
        print(f"Top {count} LinkedIn Posts for '{query}'\n")

        for i, p_data in enumerate(posts):
            print(f"Post {i+1}")
            print("Author :", p_data["author"])
            print("Text   :", p_data["text"][:300])
            print("Profile:", p_data["profileUrl"])
            print()

        context.close()

    return posts


def summarize_post(client, post):
    prompt = (
        f"Author: {post['author']}\n"
        f"Text: {post['text'][:2500]}\n\n"
        "Summarize this LinkedIn post in 1-2 sentences based only on the info above."
    )
    response = client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=[
            {
                "role": "system",
                "content": "You are a concise professional-content summarizer. Use only the given info.",
            },
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content.strip()


def generate_report(client, query, posts):
    context_text = "\n---\n".join(
        f"Author: {p['author']}\nText: {p['text'][:2500]}" for p in posts
    )
    prompt = f"""
You are a professional research analyst. Based ONLY on the LinkedIn posts below
for the search "{query}", write a short report covering:

1. Overview of professional themes/discourse
2. Recurring topics or industry angles
3. Notable authors/voices
4. Summary table (author, one-line topic)

Context:
{context_text}
"""
    response = client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=[
            {
                "role": "system",
                "content": "You are a precise research analyst. Use only the provided context.",
            },
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content.strip()


if __name__ == "__main__":
    query = input("Enter LinkedIn Search Query : ")

    posts = search_linkedin(query, max_results=5)

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