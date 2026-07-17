"""
Multi-Source AI Research Agent
===============================

Architecture:

    Fast mode (default): fallback chain, stops at first provider that works
        DuckDuckGo -> Serper -> Tavily -> Exa

    Deep Research mode (opt-in): queries EVERY provider that has a key
    configured (DuckDuckGo always, plus Serper/Tavily/Exa if keys are set),
    keeps a small number of results from each (default 3), and tags every
    source with which provider it came from - both in the console output
    and in the final report's "Sources" section.

        DuckDuckGo  \
        Serper       \
        Tavily        >---> combined, de-duplicated, provider-tagged results
        Exa          /
                    |
    Jina Reader (reads full text of every selected URL)
        |
    LLM Analysis (Groq)
        |
    Professional Research Report (saved as Markdown, provider noted per source)

Usage:
    python research_agent.py "Simulation theory"
    python research_agent.py "Quantum computing breakthroughs" --max-results 8
    python research_agent.py "AI regulation in the EU" --model gpt-4o-mini
    python research_agent.py "AI regulation in the EU" --deep   # use every provider

All API keys are read from environment variables (loaded from a .env file via
python-dotenv). GROQ_API_KEY is required. The rest are optional - if any of
them are missing, that provider is skipped.
"""

import time
import textwrap
from dataclasses import dataclass, field
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
# provider is skipped.
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
    source: str = ""  # which provider found this (duckduckgo / serper / tavily / exa)


@dataclass
class ArticleContent:
    url: str
    title: str
    text: str
    success: bool = True
    error: Optional[str] = None
    provider: str = ""  # carried over from the SearchResult that produced this URL


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


# Display names used in logs / the final report.
PROVIDER_LABELS = {
    "duckduckgo": "DuckDuckGo",
    "serper": "Serper",
    "tavily": "Tavily",
    "exa": "Exa",
}

SEARCH_CHAIN: List[Tuple[str, Callable[..., List[SearchResult]]]] = [
    ("DuckDuckGo", search_duckduckgo),
    ("Serper", search_serper),
    ("Tavily", search_tavily),
    ("Exa", search_exa),
]


def search_with_fallback(query: str, max_results: int = 5, verbose: bool = True):
    """Fast mode: try each provider in order, stop at the first one that
    returns usable results. This is the default / quick-search behavior."""
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


def search_all_providers(
    query: str, max_results_per_provider: int = 3, verbose: bool = True
) -> Tuple[List[SearchResult], List[str]]:
    """Deep Research mode: query EVERY provider that has a key configured
    (DuckDuckGo always runs since it needs no key), instead of stopping at
    the first success.

    Each provider only contributes up to `max_results_per_provider` results
    (kept small - 1 to 3 by default) so a deep search stays fast even though
    it fans out to every provider. Results are de-duplicated by URL and each
    one keeps a record of which provider found it (SearchResult.source), so
    the final report and the UI can show "found via DuckDuckGo / Serper /
    etc." next to each source.

    Returns (combined_results, providers_that_succeeded).
    """
    combined: List[SearchResult] = []
    seen_urls = set()
    providers_used: List[str] = []

    for name, func in SEARCH_CHAIN:
        try:
            if verbose:
                print(f"[deep-search] Trying {name}...")
            results = func(query, max_results=max_results_per_provider)
            new_count = 0
            for r in results:
                if r.url and r.url not in seen_urls:
                    seen_urls.add(r.url)
                    combined.append(r)
                    new_count += 1
            if verbose:
                print(f"[deep-search] {name} contributed {new_count} new result(s).")
            if new_count > 0:
                providers_used.append(name)
        except Exception as e:
            if verbose:
                print(f"[deep-search] {name} failed / skipped: {e}")
            continue

    if not combined:
        raise SearchProviderError("Deep Research failed: every provider returned no usable results.")

    return combined, providers_used


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
        self.source_max_chars = source_max_chars
        self.digest_max_tokens = digest_max_tokens
        self.article_max_tokens = article_max_tokens
        self.max_retries = max_retries
        self.seconds_between_calls = seconds_between_calls
        self.reasoning_effort = reasoning_effort
        self._model_supports_reasoning_effort = model.startswith("openai/gpt-oss")

    def _call_with_retry(self, messages, max_tokens: int, temperature: float = 0.5):
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
        print(f"Summarizing {len(articles)} source(s) individually to stay under Groq's "
              f"per-request token limit...")
        digest_blocks = []
        source_list_lines = []  # for the final "Sources" section, provider included
        for i, a in enumerate(articles, 1):
            if not a.success:
                continue
            print(f"  Summarizing source [{i}]: {a.url}")
            try:
                digest = self._summarize_source(i, a)
            except Exception as e:
                print(f"    -> Failed to summarize source [{i}], skipping it: {e}")
                continue

            print(f"    -> Digest ({len(digest)} chars): {digest[:200]}")
            if len(digest.strip()) < 40:
                print(f"    -> Digest too thin, dropping source [{i}]")
                continue

            provider_label = PROVIDER_LABELS.get(a.provider, a.provider or "unknown provider")
            digest_blocks.append(
                f"SOURCE [{i}] URL: {a.url}\nTITLE: {a.title}\nFOUND VIA: {provider_label}\nDIGEST:\n{digest}\n"
            )
            source_list_lines.append(f"{i}. [{a.title or a.url}]({a.url}) — found via {provider_label}")
            time.sleep(self.seconds_between_calls)

        if not digest_blocks:
            raise RuntimeError(
                "Every source's digest came back empty or too thin to use. This usually means "
                "Jina Reader couldn't pull real article text from those URLs (paywall, cookie "
                "wall, or JS-only page). Try different sources or a different query."
            )

        combined_digests = "\n\n".join(digest_blocks)

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
            "ones rather than declining the task. Each SOURCE block also states which search "
            "provider (FOUND VIA) surfaced it - do not fold that into the article prose, it is "
            "only for the Sources section at the end."
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
- End with a "Sources" section listing each numbered source's URL AND which
  search provider found it (use the FOUND VIA field given in each SOURCE
  block below), e.g. "1. Title (url) — found via DuckDuckGo"
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

    def research(
        self,
        topic: str,
        verbose: bool = True,
        deep_search: bool = False,
        deep_max_per_provider: int = 3,
    ):
        """
        deep_search=False (default): fast mode, fallback chain, stops at the
        first provider that returns results (current/existing behavior).

        deep_search=True: queries every configured provider (up to
        `deep_max_per_provider` results each), combines + de-dupes them, and
        tags every source with the provider that found it, both in logs and
        in the saved report's Sources section.
        """
        mode_label = "DEEP RESEARCH (all providers)" if deep_search else "Quick Research"
        print(f"\n{'=' * 60}\n{mode_label}: {topic}\n{'=' * 60}\n")

        if deep_search:
            results, providers_used = search_all_providers(
                topic, max_results_per_provider=deep_max_per_provider, verbose=verbose
            )
            provider_summary = ", ".join(providers_used) if providers_used else "none"
            print(f"\nDeep Research combined {len(results)} result(s) from: {provider_summary}")
            provider_used_label = f"Deep Search ({provider_summary})"
        else:
            results, provider_name = search_with_fallback(topic, max_results=self.max_results, verbose=verbose)
            print(f"\nUsing {len(results)} result(s) from {provider_name}:")
            provider_used_label = provider_name

        for r in results:
            label = PROVIDER_LABELS.get(r.source, r.source or "unknown")
            print(f"  - {r.title} ({r.url})  [via {label}]")

        print("\nReading full article content via Jina Reader...")
        articles = []
        for r in results:
            if not r.url:
                continue
            print(f"  Reading: {r.url}")
            content = read_url_with_jina(r.url)
            if not content.title:
                content.title = r.title
            content.provider = r.source
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

        filename = self._save_report(topic, article_markdown, provider_used_label, successful_articles)
        print(f"\nReport saved to: {filename}")
        source_urls = [a.url for a in successful_articles]
        providers_per_source = [
            {"url": a.url, "title": a.title, "provider": PROVIDER_LABELS.get(a.provider, a.provider)}
            for a in successful_articles
        ]
        return article_markdown, filename, source_urls, providers_per_source

    def _save_report(self, topic, article_markdown, provider_used, articles) -> str:
        safe_topic = "".join(c if c.isalnum() or c in " -_" else "" for c in topic).strip().replace(" ", "_")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(self.output_dir, f"{safe_topic}_{timestamp}.md")

        header = textwrap.dedent(f"""\
        <!--
        Research Report
        Topic: {topic}
        Generated: {datetime.now().isoformat()}
        Search mode: {provider_used}
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
    parser.add_argument("--max-results", type=int, default=5, help="Number of URLs to research (fast mode)")
    parser.add_argument("--output-dir", default="reports", help="Directory to save reports")
    parser.add_argument(
        "--deep", action="store_true",
        help="Deep Research mode: query every configured provider (not just the first "
             "one that works) and tag each source with the provider that found it.",
    )
    parser.add_argument(
        "--deep-max-per-provider", type=int, default=3,
        help="Max results to keep from each provider in Deep Research mode (default: 3)",
    )
    args = parser.parse_args()

    topic = " ".join(args.topic)

    agent = ResearchAgent(llm_model=args.model, max_results=args.max_results, output_dir=args.output_dir)
    article, filename, source_urls, providers_per_source = agent.research(
        topic, deep_search=args.deep, deep_max_per_provider=args.deep_max_per_provider
    )

    print("\n" + "=" * 60)
    print("FINAL ARTICLE")
    print("=" * 60 + "\n")
    print(article)

    print("\n" + "=" * 60)
    print("SOURCES BY PROVIDER")
    print("=" * 60)
    for s in providers_per_source:
        print(f"  - {s['title']} ({s['url']})  [via {s['provider']}]")


if __name__ == "__main__":
    main()