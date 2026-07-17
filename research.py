"""
Multi-Source AI Research Agent
===============================

Architecture (fallback chain):

    DuckDuckGo
        |
    Serper (optional, needs SERPER_API_KEY)
        |
    Tavily (optional, needs TAVILY_API_KEY)
        |
    Exa (optional, needs EXA_API_KEY)
        |
    Jina Reader (reads full text of every selected URL)
        |
    LLM Analysis (Groq)
        |
    Professional Research Report (saved as Markdown)

Each search provider is tried in order. If a provider has no API key configured,
raises an error, or returns zero results, the agent automatically falls back to
the next provider in the chain. DuckDuckGo requires no API key and is tried first.

Usage:
    python research_agent.py "Simulation theory"
    python research_agent.py "Quantum computing breakthroughs" --max-results 8
    python research_agent.py "AI regulation in the EU" --model gpt-4o-mini

All API keys are read from environment variables (loaded from a .env file via
python-dotenv). GROQ_API_KEY is required. The rest are optional — if any of
them are missing, that provider is skipped and the fallback chain moves on to
the next one.
"""

import time
import textwrap
from dataclasses import dataclass
from typing import List, Optional, Callable, Tuple
from datetime import datetime
import os

import requests
from dotenv import load_dotenv

try:
    from ddgs import DDGS
except ImportError:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        DDGS = None

from groq import Groq


# ---------------------------------------------------------------------------
# CONFIG - all keys come from environment variables / .env file.
# GROQ_API_KEY is required. Everything else is optional - if unset, that
# provider is skipped and the fallback chain just moves on to the next one.
# ---------------------------------------------------------------------------
load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
SERPER_API_KEY = os.getenv("SERPER_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
EXA_API_KEY = os.getenv("EXA_API_KEY")
JINA_API_KEY = os.getenv("JINA_API_KEY")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    source: str = ""


@dataclass
class ArticleContent:
    url: str
    title: str
    text: str
    success: bool = True
    error: Optional[str] = None


class SearchProviderError(Exception):
    """Raised when a search provider fails or returns no usable results."""


# ---------------------------------------------------------------------------
# Search providers
# ---------------------------------------------------------------------------

def search_duckduckgo(query: str, max_results: int = 5) -> List[SearchResult]:
    if DDGS is None:
        raise SearchProviderError("duckduckgo_search package not installed")
    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=max_results):
            results.append(SearchResult(
                title=r.get("title", ""),
                url=r.get("href", "") or r.get("url", ""),
                snippet=r.get("body", ""),
                source="duckduckgo",
            ))
    if not results:
        raise SearchProviderError("DuckDuckGo returned no results")
    return results


def search_serper(query: str, max_results: int = 5) -> List[SearchResult]:
    api_key = SERPER_API_KEY
    if not api_key:
        raise SearchProviderError("SERPER_API_KEY not set")
    resp = requests.post(
        "https://google.serper.dev/search",
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        json={"q": query, "num": max_results},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    results = [
        SearchResult(
            title=item.get("title", ""),
            url=item.get("link", ""),
            snippet=item.get("snippet", ""),
            source="serper",
        )
        for item in data.get("organic", [])[:max_results]
    ]
    if not results:
        raise SearchProviderError("Serper returned no results")
    return results


def search_tavily(query: str, max_results: int = 5) -> List[SearchResult]:
    api_key = TAVILY_API_KEY
    if not api_key:
        raise SearchProviderError("TAVILY_API_KEY not set")
    resp = requests.post(
        "https://api.tavily.com/search",
        json={"api_key": api_key, "query": query, "max_results": max_results},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    results = [
        SearchResult(
            title=item.get("title", ""),
            url=item.get("url", ""),
            snippet=item.get("content", ""),
            source="tavily",
        )
        for item in data.get("results", [])[:max_results]
    ]
    if not results:
        raise SearchProviderError("Tavily returned no results")
    return results


def search_exa(query: str, max_results: int = 5) -> List[SearchResult]:
    api_key = EXA_API_KEY
    if not api_key:
        raise SearchProviderError("EXA_API_KEY not set")
    resp = requests.post(
        "https://api.exa.ai/search",
        headers={"x-api-key": api_key, "Content-Type": "application/json"},
        json={"query": query, "numResults": max_results, "type": "auto"},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    results = [
        SearchResult(
            title=item.get("title", "") or "",
            url=item.get("url", ""),
            snippet=(item.get("text", "") or "")[:300],
            source="exa",
        )
        for item in data.get("results", [])[:max_results]
    ]
    if not results:
        raise SearchProviderError("Exa returned no results")
    return results


SEARCH_CHAIN: List[Tuple[str, Callable[..., List[SearchResult]]]] = [
    ("DuckDuckGo", search_duckduckgo),
    ("Serper", search_serper),
    ("Tavily", search_tavily),
    ("Exa", search_exa),
]


def search_with_fallback(query: str, max_results: int = 5, verbose: bool = True):
    """Try each provider in the chain in order until one succeeds."""
    last_error = None
    for name, func in SEARCH_CHAIN:
        try:
            if verbose:
                print(f"[search] Trying {name}...")
            results = func(query, max_results=max_results)
            if verbose:
                print(f"[search] {name} succeeded with {len(results)} result(s).")
            return results, name
        except Exception as e:
            last_error = e
            if verbose:
                print(f"[search] {name} failed: {e}")
            continue
    raise SearchProviderError(f"All search providers failed. Last error: {last_error}")


# ---------------------------------------------------------------------------
# Jina Reader - reads full article text for each selected URL
# ---------------------------------------------------------------------------

def read_url_with_jina(url: str, timeout: int = 30) -> ArticleContent:
    jina_key = JINA_API_KEY
    headers = {"Accept": "text/plain"}
    if jina_key:
        headers["Authorization"] = f"Bearer {jina_key}"
    reader_url = f"https://r.jina.ai/{url}"
    try:
        resp = requests.get(reader_url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        text = resp.text.strip()
        if not text:
            return ArticleContent(url=url, title="", text="", success=False, error="Empty content")
        title = ""
        for line in text.splitlines()[:5]:
            if line.strip().lower().startswith("title:"):
                title = line.split(":", 1)[1].strip()
                break
        return ArticleContent(url=url, title=title, text=text, success=True)
    except Exception as e:
        return ArticleContent(url=url, title="", text="", success=False, error=str(e))


# ---------------------------------------------------------------------------
# LLM analysis - turns raw source text into a polished article
# ---------------------------------------------------------------------------

class LLMAnalyzer:
    def __init__(
        self,
        model: str = "openai/gpt-oss-20b",
        source_max_chars: int = 4000,
        digest_max_tokens: int = 700,
        article_max_tokens: int = 2500,
        max_retries: int = 3,
        seconds_between_calls: float = 1.5,
        reasoning_effort: str = "low",
    ):
        api_key = GROQ_API_KEY
        if not api_key:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Add it to your .env file "
                "(get a key at https://console.groq.com/keys)."
            )
        self.client = Groq(api_key=api_key)
        self.model = model
        # How much raw text from a source to feed into its own summarization call.
        # Kept small so each individual call stays comfortably under Groq's
        # tokens-per-minute limit, no matter how many sources there are.
        self.source_max_chars = source_max_chars
        self.digest_max_tokens = digest_max_tokens
        self.article_max_tokens = article_max_tokens
        self.max_retries = max_retries
        self.seconds_between_calls = seconds_between_calls
        # openai/gpt-oss models are reasoning models: they spend tokens on hidden
        # "thinking" before writing the actual answer, and those tokens count
        # against max_tokens. On long/dense inputs this can burn the entire
        # budget on reasoning and leave zero tokens for the real output, so we
        # cap reasoning effort and keep max_tokens generous as headroom.
        self.reasoning_effort = reasoning_effort
        self._model_supports_reasoning_effort = model.startswith("openai/gpt-oss")

    def _call_with_retry(self, messages, max_tokens: int, temperature: float = 0.5):
        """Call the Groq chat completion endpoint, retrying with backoff on
        rate-limit / payload-too-large errors (HTTP 429 / 413)."""
        delay = 3
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                kwargs = dict(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                if self._model_supports_reasoning_effort:
                    kwargs["reasoning_effort"] = self.reasoning_effort
                response = self.client.chat.completions.create(**kwargs)

                # Reasoning models can still come back with empty content if they
                # exhaust max_tokens on hidden reasoning. Detect that and retry
                # once with a larger budget instead of silently returning "".
                content = (response.choices[0].message.content or "").strip()
                finish_reason = response.choices[0].finish_reason
                if not content and finish_reason == "length" and attempt < self.max_retries:
                    bumped = int(max_tokens * 1.6)
                    print(f"[llm] Empty response (used entire budget on reasoning), "
                          f"retrying with max_tokens={bumped}...")
                    max_tokens = bumped
                    continue

                return response
            except Exception as e:
                last_error = e
                msg = str(e).lower()
                is_rate_or_size_error = (
                    "rate_limit" in msg or "429" in msg or "413" in msg or "too large" in msg
                )
                if not is_rate_or_size_error or attempt == self.max_retries:
                    raise
                print(f"[llm] Hit a rate/size limit (attempt {attempt}/{self.max_retries}), "
                      f"waiting {delay}s before retrying...")
                time.sleep(delay)
                delay *= 2
        raise last_error

    def _summarize_source(self, index: int, article: ArticleContent) -> str:
        """Turn one source's raw text into a short factual digest via its own
        small LLM call, instead of stuffing the full text into the final prompt."""
        snippet = article.text[: self.source_max_chars]
        prompt = (
            f"URL: {article.url}\n"
            f"TITLE: {article.title}\n\n"
            f"CONTENT:\n{snippet}\n\n"
            "Write a tight 120-180 word factual digest of this source: the key "
            "facts, figures, claims, and any notable quotes. No commentary or "
            "opinions beyond what's in the text."
        )
        response = self._call_with_retry(
            messages=[
                {
                    "role": "system",
                    "content": "You are a research assistant producing a factual digest of a single "
                               "source. Use only the given text, never outside knowledge.",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=self.digest_max_tokens,
            temperature=0.3,
        )
        return (response.choices[0].message.content or "").strip()



    def write_article(self, topic: str, articles: List[ArticleContent]) -> str:
        # Stage 1: summarize each source individually. Each call only sends one
        # source's (truncated) text, so no single request comes close to the
        # tokens-per-minute cap - no matter how many sources or how long they are.
        print(f"Summarizing {len(articles)} source(s) individually to stay under Groq's "
              f"per-request token limit...")
        digest_blocks = []
        for i, a in enumerate(articles, 1):
            if not a.success:
                continue
            print(f"  Summarizing source [{i}]: {a.url}")
            try:
                digest = self._summarize_source(i, a)
            except Exception as e:
                print(f"    -> Failed to summarize source [{i}], skipping it: {e}")
                continue

            # A digest under ~40 chars almost always means the page had nothing
            # usable (cookie banner, paywall, JS-only content) rather than a real
            # article - print it so it's visible, and drop it so thin/empty
            # digests don't drag the final article down or trigger a refusal.
            print(f"    -> Digest ({len(digest)} chars): {digest[:200]}")
            if len(digest.strip()) < 40:
                print(f"    -> Digest too thin, dropping source [{i}]")
                continue

            digest_blocks.append(
                f"SOURCE [{i}] URL: {a.url}\nTITLE: {a.title}\nDIGEST:\n{digest}\n"
            )
            time.sleep(self.seconds_between_calls)  # space calls out across the per-minute window

        if not digest_blocks:
            raise RuntimeError(
                "Every source's digest came back empty or too thin to use. This usually means "
                "Jina Reader couldn't pull real article text from those URLs (paywall, cookie "
                "wall, or JS-only page). Try different sources or a different query."
            )

        combined_digests = "\n\n".join(digest_blocks)

        # Stage 2: write the final article from the (much shorter) digests rather
        # than the raw source text - this second call is also comfortably small.
        system_prompt = (
            "You are a senior investigative journalist and researcher at The New York Times. "
            "You write rigorous, well-structured, engaging long-form articles based strictly on "
            "the provided source digests. You never fabricate facts or quotes. You cite sources "
            "inline using bracketed numbers like [1], [2] that correspond to the numbered SOURCE "
            "blocks given to you. You write in clear, precise NYT house style: a strong lede, a "
            "clear nut graph, a well-organized body with subheadings, and a thoughtful conclusion. "
            "You always deliver a finished article using whatever material you were given - you "
            "never refuse, apologize, or ask for more information. If some digests are thinner "
            "than others, you lean on the richer ones and write shorter sections for the thin "
            "ones rather than declining the task."
        )

        user_prompt = f"""Topic: {topic}

You have been given {len(digest_blocks)} source digests below (each one already
summarized from a full article). Read them carefully, cross-reference facts,
note points of agreement and disagreement between sources, and then write a
polished, NYT-quality feature article on this topic using ONLY this material.

Requirements:
- Compelling headline
- Byline line: "By Claude Research Desk" and today's date
- Length scaled to the material available (aim for 900-1400 words if the
  digests support it, shorter is fine if they don't - never pad with filler)
- Use subheadings to organize the piece
- Cite sources inline as [1], [2], etc. matching the SOURCE numbers below
- End with a "Sources" section listing each numbered source's URL
- Output in Markdown
- Do not refuse, apologize, or ask for more information - write the best
  possible article from what's given below, even if it's brief

{combined_digests}
"""

        print("Writing final article from source digests...")
        response = self._call_with_retry(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=self.article_max_tokens,
            temperature=0.7,
        )
        article = (response.choices[0].message.content or "").strip()

        # Safety net: if the model refused anyway, push back once with a
        # sterner, more explicit instruction instead of silently returning
        # the refusal text as if it were the article.
        refusal_markers = ("i'm sorry", "i am sorry", "i can't produce", "i cannot produce",
                            "i can't write", "i cannot write")
        if (not article or (len(article) < 300 and article.lower().startswith(refusal_markers))):
            print("[llm] Model refused instead of writing the article - retrying with a "
                  "stricter instruction...")
            response = self._call_with_retry(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                    {"role": "assistant", "content": article or "(empty response)"},
                    {
                        "role": "user",
                        "content": "That was a refusal, not an article. You are required to write "
                                   "the article now using only the SOURCE digests already given "
                                   "above. Do not apologize or explain limitations - output the "
                                   "Markdown article directly, starting with the headline.",
                    },
                ],
                max_tokens=self.article_max_tokens,
                temperature=0.7,
            )
            article = (response.choices[0].message.content or "").strip()

        return article


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class ResearchAgent:
    def __init__(self, llm_model: str = "gpt-4o", max_results: int = 5, output_dir: str = "reports"):
        self.max_results = max_results
        self.analyzer = LLMAnalyzer(model=llm_model)
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def research(self, topic: str, verbose: bool = True):
        print(f"\n{'=' * 60}\nResearching topic: {topic}\n{'=' * 60}\n")

        results, provider_used = search_with_fallback(topic, max_results=self.max_results, verbose=verbose)

        print(f"\nUsing {len(results)} result(s) from {provider_used}:")
        for r in results:
            print(f"  - {r.title} ({r.url})")

        print("\nReading full article content via Jina Reader...")
        articles = []
        for r in results:
            if not r.url:
                continue
            print(f"  Reading: {r.url}")
            content = read_url_with_jina(r.url)
            if not content.title:
                content.title = r.title
            if content.success:
                print(f"    -> OK ({len(content.text)} chars)")
            else:
                print(f"    -> Failed: {content.error}")
            articles.append(content)
            time.sleep(0.5)  # be polite to the reader endpoint

        successful_articles = [a for a in articles if a.success]
        if not successful_articles:
            raise RuntimeError("Could not read any article content. Aborting.")

        print(f"\nSuccessfully read {len(successful_articles)}/{len(articles)} article(s).")
        print("Sending content to LLM for analysis and article writing...\n")

        article_markdown = self.analyzer.write_article(topic, successful_articles)

        filename = self._save_report(topic, article_markdown, provider_used, successful_articles)
        print(f"\nReport saved to: {filename}")
        source_urls = [a.url for a in successful_articles]
        return article_markdown, filename, source_urls

    def _save_report(self, topic, article_markdown, provider_used, articles) -> str:
        safe_topic = "".join(c if c.isalnum() or c in " -_" else "" for c in topic).strip().replace(" ", "_")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(self.output_dir, f"{safe_topic}_{timestamp}.md")

        header = textwrap.dedent(f"""\
        <!--
        Research Report
        Topic: {topic}
        Generated: {datetime.now().isoformat()}
        Search provider used: {provider_used}
        Sources read: {len(articles)}
        -->

        """)

        with open(filename, "w", encoding="utf-8") as f:
            f.write(header)
            f.write(article_markdown)

        return filename


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Multi-source AI research agent")
    parser.add_argument("topic", nargs="*", default=["Simulation theory"], help="Research topic")
    parser.add_argument("--model", default="openai/gpt-oss-20b", help="Groq model for analysis")
    parser.add_argument("--max-results", type=int, default=5, help="Number of URLs to research")
    parser.add_argument("--output-dir", default="reports", help="Directory to save reports")
    args = parser.parse_args()

    topic = " ".join(args.topic)

    agent = ResearchAgent(llm_model=args.model, max_results=args.max_results, output_dir=args.output_dir)
    article, filename, source_urls = agent.research(topic)

    print("\n" + "=" * 60)
    print("FINAL ARTICLE")
    print("=" * 60 + "\n")
    print(article)


if __name__ == "__main__":
    main()