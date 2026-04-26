from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from app.models import Reference


async def semantic_scholar_search(question: str, limit: int = 10) -> list[Reference]:
    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    params = {
        "query": question,
        "limit": limit,
        "fields": "title,url,venue,year,authors,abstract,externalIds",
    }
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            data: dict[str, Any] = r.json()
    except Exception:
        return []

    refs: list[Reference] = []
    for item in (data.get("data") or [])[:limit]:
        abstract = item.get("abstract") or None
        snippet = (abstract[:280] + "…") if abstract and len(abstract) > 280 else abstract
        ext = item.get("externalIds") or {}
        doi = ext.get("DOI") or ext.get("doi")
        arxiv_id = ext.get("ArXiv") or ext.get("arxiv")
        if not doi and arxiv_id:
            doi = f"10.48550/arXiv.{arxiv_id}"
        refs.append(
            Reference(
                title=item.get("title") or "Untitled",
                url=item.get("url"),
                venue=item.get("venue"),
                year=item.get("year"),
                authors=[a.get("name") for a in (item.get("authors") or []) if a.get("name")],
                snippet=snippet,
                source="Semantic Scholar",
                doi=doi,
            )
        )
    return refs


async def arxiv_search(question: str, limit: int = 10) -> list[Reference]:
    import re
    import xml.etree.ElementTree as ET
    from urllib.parse import quote_plus

    url = f"https://export.arxiv.org/api/query?search_query=all:{quote_plus(question)}&start=0&max_results={limit}"
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            r = await client.get(url)
            r.raise_for_status()
            xml = r.text
    except Exception:
        return []

    ns = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []

    out: list[Reference] = []
    for entry in root.findall("a:entry", ns)[:limit]:
        title = (entry.findtext("a:title", default="", namespaces=ns) or "").strip().replace("\n", " ")
        summary = (entry.findtext("a:summary", default="", namespaces=ns) or "").strip().replace("\n", " ")
        snippet = (summary[:280] + "…") if summary and len(summary) > 280 else (summary or None)
        link = None
        for l in entry.findall("a:link", ns):
            if l.attrib.get("rel") == "alternate":
                link = l.attrib.get("href")
                break

        # Year from <published>YYYY-MM-DDTHH:MM:SSZ</published>
        published = entry.findtext("a:published", default="", namespaces=ns) or ""
        year: int | None = None
        m = re.match(r"^(\d{4})", published)
        if m:
            try:
                year = int(m.group(1))
            except ValueError:
                year = None

        # Canonical arXiv id from <id>http://arxiv.org/abs/XXXX.YYYYY[vN]</id>
        raw_id = entry.findtext("a:id", default="", namespaces=ns) or ""
        arxiv_id: str | None = None
        m2 = re.search(r"arxiv\.org/abs/([^/\s]+)$", raw_id)
        if m2:
            arxiv_id = re.sub(r"v\d+$", "", m2.group(1))

        # Prefer publisher DOI if arxiv reports one, else synthesize the arXiv-assigned DataCite DOI.
        pub_doi = (entry.findtext("arxiv:doi", default="", namespaces=ns) or "").strip() or None
        doi = pub_doi or (f"10.48550/arXiv.{arxiv_id}" if arxiv_id else None)

        authors = [a.findtext("a:name", default="", namespaces=ns) for a in entry.findall("a:author", ns)]
        out.append(
            Reference(
                title=title or "Untitled",
                url=link,
                venue="arXiv",
                year=year,
                authors=[a for a in authors if a],
                snippet=snippet,
                source="arXiv",
                doi=doi,
            )
        )
    return out


async def tavily_search(question: str, api_key: str, limit: int = 8) -> list[Reference]:
    """Web search powered by Tavily. Returns references with snippets."""
    if not api_key:
        return []
    url = "https://api.tavily.com/search"
    payload = {
        "api_key": api_key,
        "query": question,
        "search_depth": "advanced",
        "include_answer": False,
        "max_results": limit,
    }
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            r = await client.post(url, json=payload)
            r.raise_for_status()
            data: dict[str, Any] = r.json()
    except Exception:
        return []

    out: list[Reference] = []
    for item in (data.get("results") or [])[:limit]:
        title = item.get("title") or "Untitled"
        link = item.get("url")
        content = item.get("content") or ""
        snippet = (content[:280] + "…") if len(content) > 280 else (content or None)
        venue = None
        if link:
            try:
                venue = urlparse(link).netloc or None
            except Exception:
                venue = None
        out.append(
            Reference(
                title=title,
                url=link,
                venue=venue,
                year=None,
                authors=[],
                snippet=snippet,
                source="Tavily",
            )
        )
    return out


def novelty_score_from_titles(question: str, refs: list[Reference]) -> tuple[float | None, str]:
    """
    Roadmap asks for a novelty score float + rationale.
    We compute a simple overlap-based similarity vs top reference titles and invert it:
    higher similarity => lower novelty.
    """
    import re

    q = re.sub(r"[^a-z0-9 ]+", " ", question.lower())
    q_tokens = {t for t in q.split() if len(t) > 3}
    if not q_tokens or not refs:
        return None, "Insufficient signal (no query tokens or no references)."

    best = 0.0
    best_title = None
    for r in refs[:10]:
        t = re.sub(r"[^a-z0-9 ]+", " ", (r.title or "").lower())
        t_tokens = {x for x in t.split() if len(x) > 3}
        if not t_tokens:
            continue
        overlap = len(q_tokens & t_tokens) / max(1, len(q_tokens))
        if overlap > best:
            best = overlap
            best_title = r.title
    novelty = max(0.0, min(1.0, 1.0 - best))
    rationale = f"Best title-token overlap={best:.2f}" + (f" (closest: {best_title})" if best_title else "")
    return novelty, rationale

