#!/usr/bin/env python3
"""Football research pipeline: ingest → detect trends → multi-agent deep research report."""

import json, logging, os, re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

import anthropic, openai, psycopg

log = logging.getLogger("research")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

ROOT = Path(__file__).resolve().parent
GATEWAY = os.environ["CLOUDFLARE_GATEWAY_URL"].rstrip("/")
TRANSCRIPT_KEY = os.environ["TRANSCRIPT_API_KEY"]
LEAD_MODEL = os.environ.get("CLAUDE_LEAD_MODEL", "claude-opus-4-0-20250514")
MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-5-20250514")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "text-embedding-3-small")

claude = anthropic.Anthropic(
    api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
    base_url=f"{GATEWAY}/anthropic",
)
oai = openai.OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY", ""),
    base_url=f"{GATEWAY}/openai",
)

CITATION_FMT = "Cite every claim as [S<source_id>:C<chunk_id>]. Never cite IDs not in the provided context."

# ══════════════════════════════════════════════
# Feed parsing
# ══════════════════════════════════════════════

def parse_feeds(path):
    text = path.read_text()
    names = [m.group(1) for m in re.finditer(r"^-\s+\*\*(.+?)\*\*", text, re.M)]
    urls = [m.group(1) for m in re.finditer(r"^\s+-\s+Feed:\s*(\S+)", text, re.M)]
    return list(zip(names, urls))

def parse_youtube(path):
    text = path.read_text()
    names = [m.group(1) for m in re.finditer(r"^-\s+\*\*(.+?)\*\*", text, re.M)]
    cids = [m.group(1) for m in re.finditer(r"^\s+-\s+Channel ID:\s*(\S+)", text, re.M)]
    return list(zip(names, cids))

def strip_html(html):
    return re.sub(r"<[^>]+>", "", html).strip()

# ══════════════════════════════════════════════
# RSS ingestion
# ══════════════════════════════════════════════

NS = {"atom": "http://www.w3.org/2005/Atom", "content": "http://purl.org/rss/1.0/modules/content/"}

def _txt(el):
    return (el.text or "").strip() if el is not None else ""

def _get(url, headers=None, timeout=15):
    req = Request(url, headers=headers or {"User-Agent": "ResearchBot/1.0"})
    with urlopen(req, timeout=timeout) as r:
        return r.read()

def fetch_rss(name, url):
    try:
        xml_bytes = _get(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; ResearchBot/1.0)",
            "Accept": "application/rss+xml, application/atom+xml, */*",
        })
        root = ET.fromstring(xml_bytes)
    except Exception as e:
        log.warning("Feed %s failed: %s", name, e)
        return []

    items = []
    if root.tag.endswith("feed"):  # Atom
        for entry in root.findall("atom:entry", NS)[:10]:
            link = entry.find("atom:link[@rel='alternate']", NS) or entry.find("atom:link", NS)
            href = (link.attrib.get("href", "") if link is not None else "").strip()
            content = strip_html(_txt(entry.find("atom:content", NS)) or _txt(entry.find("atom:summary", NS)))
            if content:
                items.append({"title": _txt(entry.find("atom:title", NS)), "url": href,
                              "content": content, "key": f"rss:{href or _txt(entry.find('atom:id', NS))}"})
    else:  # RSS 2.0
        for item in root.findall("./channel/item")[:10]:
            content = strip_html(_txt(item.find("content:encoded", NS)) or _txt(item.find("description")))
            item_url = _txt(item.find("link"))
            if content:
                items.append({"title": _txt(item.find("title")), "url": item_url,
                              "content": content, "key": f"rss:{_txt(item.find('guid')) or item_url}"})
    return items

# ══════════════════════════════════════════════
# YouTube ingestion
# ══════════════════════════════════════════════

YT_NS = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}

def fetch_youtube(name, channel_id):
    try:
        xml_bytes = _get(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}")
        root = ET.fromstring(xml_bytes)
    except Exception as e:
        log.warning("YouTube %s failed: %s", name, e)
        return []

    items = []
    for entry in root.findall("atom:entry", YT_NS)[:5]:
        vid = (entry.findtext("yt:videoId", default="", namespaces=YT_NS) or "").strip()
        if not vid:
            continue
        title = (entry.findtext("atom:title", default="", namespaces=YT_NS) or "").strip()
        try:
            turl = f"https://transcriptapi.com/api/v2/youtube/transcript?{urlencode({'video_url': f'https://www.youtube.com/watch?v={vid}'})}"
            data = json.loads(_get(turl, headers={"Authorization": f"Bearer {TRANSCRIPT_KEY}", "Accept": "application/json"}))
            transcript = ""
            for k in ("transcript", "text", "content"):
                v = data.get(k)
                if isinstance(v, str): transcript = v; break
                if isinstance(v, list): transcript = " ".join(p.get("text", "") for p in v if isinstance(p, dict)); break
        except Exception as e:
            log.warning("Transcript %s failed: %s", vid, e)
            continue
        if transcript.strip():
            items.append({"title": title, "url": f"https://www.youtube.com/watch?v={vid}",
                          "content": transcript.strip(), "key": f"yt:{channel_id}:{vid}"})
    return items

# ══════════════════════════════════════════════
# Storage & embedding
# ══════════════════════════════════════════════

def store_source(conn, item, source_type):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sources (source_type, source_key, title, url, content) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (source_key) DO NOTHING RETURNING id",
            (source_type, item["key"], item["title"], item["url"], item["content"]),
        )
        row = cur.fetchone()
        conn.commit()
        return row[0] if row else None

def embed(texts):
    """Embed a list of texts via OpenAI through Cloudflare."""
    return [d.embedding for d in oai.embeddings.create(model=EMBED_MODEL, input=texts).data]

def vec_literal(vec):
    return "[" + ",".join(str(v) for v in vec) + "]"

def chunk_and_embed(conn, source_id, text):
    words = text.split()
    if not words:
        return
    chunks = []
    for i in range(0, len(words), 160):
        chunk = " ".join(words[i:i + 200])
        if chunk.strip():
            chunks.append(chunk.strip())
        if i + 200 >= len(words):
            break
    if not chunks:
        return

    vectors = embed(chunks)
    with conn.cursor() as cur:
        for idx, (chunk, vec) in enumerate(zip(chunks, vectors)):
            cur.execute(
                "INSERT INTO chunks (source_id, chunk_index, content, embedding) "
                "VALUES (%s, %s, %s, %s::vector) ON CONFLICT (source_id, chunk_index) DO NOTHING",
                (source_id, idx, chunk, vec_literal(vec)),
            )
        conn.commit()

# ══════════════════════════════════════════════
# Hybrid retrieval (semantic + keyword via RRF)
# ══════════════════════════════════════════════

def hybrid_search(conn, query, limit=20):
    """Retrieve chunks using hybrid RRF search (vector + full-text)."""
    qvec = embed([query])[0]
    with conn.cursor() as cur:
        cur.execute(
            "SELECT h.chunk_id, h.source_id, h.content, s.title, s.url, h.score "
            "FROM hybrid_search(%s, %s::vector, %s) h "
            "JOIN sources s ON s.id = h.source_id",
            (query, vec_literal(qvec), limit),
        )
        return cur.fetchall()

def chunks_to_json(rows):
    """Format retrieved chunk rows as a JSON context packet."""
    return json.dumps([
        {"chunk_id": cid, "source_id": sid, "content": content,
         "source_title": title, "source_url": url}
        for cid, sid, content, title, url, *_ in rows
    ], indent=2)

# ══════════════════════════════════════════════
# Claude helpers
# ══════════════════════════════════════════════

def ask(system, user, model=None, max_tokens=4096):
    """Send a system+user message to Claude, return text."""
    resp = claude.messages.create(
        model=model or MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return resp.content[0].text

def ask_json(system, user, model=None):
    """Ask Claude and parse JSON from response."""
    text = ask(system, user, model=model)
    match = re.search(r"[\[{].*[\]}]", text, re.DOTALL)
    if match:
        return json.loads(match.group())
    raise ValueError(f"No JSON found in response: {text[:200]}")

# ══════════════════════════════════════════════
# Trend detection
# ══════════════════════════════════════════════

def detect_trends(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT title, LEFT(content, 500) FROM sources "
            "WHERE created_at > NOW() - INTERVAL '7 days' ORDER BY created_at DESC LIMIT 100"
        )
        recent = cur.fetchall()
    if not recent:
        return None

    summaries = "\n".join(f"- {t}: {c}..." for t, c in recent)
    with conn.cursor() as cur:
        cur.execute("SELECT title FROM reports ORDER BY created_at DESC LIMIT 10")
        past = [r[0] for r in cur.fetchall()]
    past_block = "\n".join(f"- {t}" for t in past) if past else "(none)"

    try:
        data = ask_json(
            "You are a football tactics analyst spotting novel trends before they go mainstream.",
            f"Recent articles and transcripts:\n{summaries}\n\n"
            f"Already-covered topics (avoid repeating):\n{past_block}\n\n"
            "Identify the single most novel tactical or strategic trend being tried by football "
            "players or teams. Something new that hasn't been widely adopted yet.\n\n"
            'Return JSON: {{"trend": "<10-20 word description>", "reasoning": "<why novel>"}}'
        )
        return data.get("trend")
    except Exception as e:
        log.warning("Trend detection failed: %s", e)
        return None

# ══════════════════════════════════════════════
# Step 1: Lead agent — decompose topic into angles
# ══════════════════════════════════════════════

def decompose_topic(trend):
    """Lead agent breaks the trend into non-overlapping research angles."""
    tasks = ask_json(
        "You are a lead research orchestrator. Break a topic into non-overlapping "
        "subagent tasks with clear boundaries so work is parallelisable and non-duplicative.",

        f"Topic: {trend}\n\n"
        "Canonical angles (choose the subset needed):\n"
        "1. Latest developments and adoption examples\n"
        "2. Technical/tactical method and implementation details\n"
        "3. Limitations, risks, and failure modes\n"
        "4. League/competition-level implications\n"
        "5. Quantitative evidence and key statistics\n"
        "6. Historical precedent and evolution\n"
        "7. Open questions and future trajectory\n\n"
        "Assess complexity: simple (1-2 angles), moderate (3-4), complex (5-7).\n\n"
        "Return JSON array. Each object must have:\n"
        '- "angle": short name\n'
        '- "objective": what this subagent must cover\n'
        '- "search_queries": array of 2-3 retrieval queries\n'
        '- "boundaries": what is explicitly out of scope\n',
        model=LEAD_MODEL,
    )
    if isinstance(tasks, dict):
        tasks = tasks.get("tasks") or tasks.get("task_descriptions") or [tasks]
    log.info("Lead agent decomposed into %d angles: %s", len(tasks), [t.get("angle") for t in tasks])
    return tasks

# ══════════════════════════════════════════════
# Step 2: Subagent — iterative retrieval per angle
# ══════════════════════════════════════════════

def research_angle(conn, trend, task, max_rounds=3):
    """Subagent: iterative search → evaluate sufficiency → narrow → search again."""
    angle = task.get("angle", "general")
    objective = task.get("objective", "")
    queries = task.get("search_queries", [f"{trend} {angle}"])
    boundaries = task.get("boundaries", "")
    all_chunks = {}  # chunk_id -> row, deduplicated

    for round_num in range(max_rounds):
        query = queries[round_num] if round_num < len(queries) else queries[-1]
        rows = hybrid_search(conn, query, limit=15)
        for row in rows:
            all_chunks[row[0]] = row  # dedup by chunk_id

        if not all_chunks:
            continue

        # Evaluate sufficiency
        chunk_json = chunks_to_json(list(all_chunks.values()))
        try:
            eval_result = ask_json(
                "Evaluate whether enough evidence exists for the research angle, or if more retrieval is needed.",
                f"Angle: {angle}\nObjective: {objective}\nRound: {round_num + 1}/{max_rounds}\n\n"
                f"Chunks collected ({len(all_chunks)} total):\n{chunk_json}\n\n"
                'Return JSON: {{"sufficient": true/false, "gaps": ["..."], "next_query": "..." or null}}'
            )
        except Exception:
            break

        if eval_result.get("sufficient", False) or round_num == max_rounds - 1:
            break

        # Use suggested narrowing query for next round
        next_q = eval_result.get("next_query")
        if next_q:
            queries.append(next_q)

    if not all_chunks:
        return {"angle": angle, "summary": f"No evidence found for: {angle}", "chunks": []}

    # Write grounded summary for this angle
    chunk_json = chunks_to_json(list(all_chunks.values()))
    summary = ask(
        f"You are a focused research subagent. Stay strictly within your assigned boundaries. {CITATION_FMT}",
        f"Angle: {angle}\nObjective: {objective}\n"
        f"Out of scope: {boundaries}\n\n"
        f"Evidence chunks:\n{chunk_json}\n\n"
        "Write a concise, evidence-grounded summary for this angle with inline citations."
    )
    log.info("Subagent '%s' done: %d chunks, %d rounds", angle, len(all_chunks), round_num + 1)
    return {"angle": angle, "summary": summary, "chunks": list(all_chunks.values())}

# ══════════════════════════════════════════════
# Step 3: Synthesis — merge subagent outputs
# ══════════════════════════════════════════════

def synthesize(trend, subagent_results):
    """Merge parallel subagent summaries into a cohesive draft report."""
    summaries_text = "\n\n---\n\n".join(
        f"### Angle: {r['angle']}\n\n{r['summary']}" for r in subagent_results
    )
    # Deduplicate all chunks across subagents
    all_chunks = {}
    for r in subagent_results:
        for row in r["chunks"]:
            all_chunks[row[0]] = row
    chunk_json = chunks_to_json(list(all_chunks.values()))

    failed = [r["angle"] for r in subagent_results if not r["chunks"]]
    failed_text = ", ".join(failed) if failed else "(none)"

    return ask(
        f"You are a synthesis editor combining multiple subagent outputs into one coherent cited markdown report. {CITATION_FMT}",
        f"Topic: {trend}\n\n"
        f"Subagent summaries:\n{summaries_text}\n\n"
        f"All deduplicated evidence chunks:\n{chunk_json}\n\n"
        f"Failed angles (limited evidence): {failed_text}\n\n"
        "Produce a comprehensive markdown report:\n"
        "- Descriptive H1 title\n"
        "- Numbered H2 sections with topic-specific angle headings\n"
        "- H3 subsections where depth warrants it\n"
        "- **Bold** key figures and statistics inline\n"
        "- Tables for structured comparisons when useful\n"
        "- `---` separators between major sections\n"
        "- Standalone ## Conclusion section\n"
        "- Acknowledge failed angles in relevant sections\n"
        "- Inline citations [S<source_id>:C<chunk_id>] on every substantive claim",
        max_tokens=12000,
    ), chunk_json

# ══════════════════════════════════════════════
# Step 4: Critique — evaluate grounding
# ══════════════════════════════════════════════

def critique(trend, draft, chunk_json):
    """Review the draft for hallucinations, unsupported claims, and weak grounding."""
    return ask(
        "You are an impartial research critic. Evaluate ONLY against provided source chunks. "
        "Flag any claim not directly supported by evidence.",
        f"Topic: {trend}\n\n"
        f"Source chunks:\n{chunk_json}\n\n"
        f"Draft report:\n{draft}\n\n"
        "Evaluate the draft. Return markdown with sections:\n"
        "## Grounding Assessment\nOverall grounding quality.\n"
        "## Hallucination Risks\nSpecific unsupported claims with exact sentence quotes.\n"
        "## Missing Evidence\nGaps where claims lack citations.\n"
        "## Citation Errors\nIncorrect or non-existent source/chunk IDs.\n"
        "## Revision Directives\nBulleted list of specific changes to make.",
    )

# ══════════════════════════════════════════════
# Step 5: Revision — incorporate critique
# ══════════════════════════════════════════════

def revise(trend, draft, critique_text, chunk_json):
    """Produce the final report incorporating critique feedback."""
    return ask(
        f"You are a revision editor producing the final research report. {CITATION_FMT}",
        f"Topic: {trend}\n\n"
        f"Source chunks:\n{chunk_json}\n\n"
        f"Draft report:\n{draft}\n\n"
        f"Critique:\n{critique_text}\n\n"
        "Produce a final revised markdown report that:\n"
        "1. Removes or qualifies every unsupported claim flagged in the critique\n"
        "2. Fixes all citation errors\n"
        "3. Fills evidence gaps where chunks support it\n"
        "4. Preserves well-grounded claims and their citations\n"
        "5. Maintains the report structure:\n"
        "   # Title\n"
        "   ## Executive Summary\n"
        "   ## Key Findings (numbered)\n"
        "   ## [Angle-specific sections]\n"
        "   ## Evidence Assessment\n"
        "   ## Implications\n"
        "   ## Open Questions\n"
        "   ## Sources\n"
        "6. Bolds key statistics, uses tables where appropriate\n"
        "7. Explicitly flags remaining speculation as such",
        max_tokens=12000,
    )

# ══════════════════════════════════════════════
# Orchestration: full multi-agent pipeline
# ══════════════════════════════════════════════

def generate_report(conn, trend):
    """Full pipeline: decompose → parallel subagents → synthesize → critique → revise."""

    # 1. Lead agent decomposes topic
    log.info("Step 1/5: Lead agent decomposing topic...")
    tasks = decompose_topic(trend)

    # 2. Parallel subagent research with iterative retrieval
    log.info("Step 2/5: Running %d subagents in parallel...", len(tasks))
    subagent_results = []
    with ThreadPoolExecutor(max_workers=min(len(tasks), 4)) as pool:
        futures = {pool.submit(research_angle, conn, trend, task): task for task in tasks}
        for future in as_completed(futures):
            try:
                subagent_results.append(future.result())
            except Exception as e:
                task = futures[future]
                log.warning("Subagent '%s' failed: %s", task.get("angle"), e)
                subagent_results.append({"angle": task.get("angle", "?"), "summary": f"Research failed: {e}", "chunks": []})

    # 3. Synthesis
    log.info("Step 3/5: Synthesizing subagent outputs...")
    draft, chunk_json = synthesize(trend, subagent_results)

    # 4. Critique
    log.info("Step 4/5: Critiquing draft for grounding...")
    critique_text = critique(trend, draft, chunk_json)

    # 5. Revision
    log.info("Step 5/5: Revising based on critique...")
    final_report = revise(trend, draft, critique_text, chunk_json)

    # Save
    metadata = json.dumps({
        "angles": [r["angle"] for r in subagent_results],
        "total_chunks": sum(len(r["chunks"]) for r in subagent_results),
        "model": MODEL,
        "lead_model": LEAD_MODEL,
    })
    with conn.cursor() as cur:
        cur.execute("INSERT INTO reports (title, content, metadata) VALUES (%s, %s, %s::jsonb)", (trend, final_report, metadata))
        conn.commit()

    slug = re.sub(r"[^a-z0-9]+", "-", trend.lower()).strip("-")[:60]
    out = ROOT / "reports" / f"{datetime.now().strftime('%Y-%m-%d')}-{slug}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(final_report)
    log.info("Report saved: %s", out)
    return final_report

# ══════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════

def main():
    conn = psycopg.connect(os.environ["POSTGRES_DSN"])
    new = 0

    for name, url in parse_feeds(ROOT / "feeds" / "rss.md"):
        for item in fetch_rss(name, url):
            sid = store_source(conn, item, "rss")
            if sid:
                chunk_and_embed(conn, sid, item["content"])
                new += 1

    for name, cid in parse_youtube(ROOT / "feeds" / "youtube.md"):
        for item in fetch_youtube(name, cid):
            sid = store_source(conn, item, "youtube")
            if sid:
                chunk_and_embed(conn, sid, item["content"])
                new += 1

    log.info("Ingested %d new sources", new)

    trend = detect_trends(conn)
    if trend:
        log.info("Detected trend: %s", trend)
        generate_report(conn, trend)
    else:
        log.info("No novel trend detected this run")

    conn.close()

if __name__ == "__main__":
    main()
