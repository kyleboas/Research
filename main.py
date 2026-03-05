#!/usr/bin/env python3
"""Football research pipeline: ingest → detect trends → generate report."""

import json, logging, os, re
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

# --- Feed parsing ---

def parse_feeds(path):
    """Parse markdown feed file -> list of (name, url)."""
    text = path.read_text()
    names = [m.group(1) for m in re.finditer(r"^-\s+\*\*(.+?)\*\*", text, re.M)]
    urls = [m.group(1) for m in re.finditer(r"^\s+-\s+Feed:\s*(\S+)", text, re.M)]
    return list(zip(names, urls))

def parse_youtube(path):
    """Parse youtube markdown -> list of (name, channel_id)."""
    text = path.read_text()
    names = [m.group(1) for m in re.finditer(r"^-\s+\*\*(.+?)\*\*", text, re.M)]
    cids = [m.group(1) for m in re.finditer(r"^\s+-\s+Channel ID:\s*(\S+)", text, re.M)]
    return list(zip(names, cids))

def strip_html(html):
    return re.sub(r"<[^>]+>", "", html).strip()

# --- RSS ingestion ---

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

# --- YouTube ingestion ---

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
            url = f"https://transcriptapi.com/api/v2/youtube/transcript?{urlencode({'video_url': f'https://www.youtube.com/watch?v={vid}'})}"
            data = json.loads(_get(url, headers={"Authorization": f"Bearer {TRANSCRIPT_KEY}", "Accept": "application/json"}))
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

# --- Storage ---

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

    vectors = [d.embedding for d in oai.embeddings.create(model=EMBED_MODEL, input=chunks).data]
    with conn.cursor() as cur:
        for idx, (chunk, vec) in enumerate(zip(chunks, vectors)):
            cur.execute(
                "INSERT INTO chunks (source_id, chunk_index, content, embedding) "
                "VALUES (%s, %s, %s, %s::vector) ON CONFLICT (source_id, chunk_index) DO NOTHING",
                (source_id, idx, chunk, "[" + ",".join(str(v) for v in vec) + "]"),
            )
        conn.commit()

# --- Trend detection ---

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

    resp = claude.messages.create(model=MODEL, max_tokens=1024, messages=[{"role": "user", "content": (
        "You are a football tactics analyst spotting novel trends before they go mainstream.\n\n"
        f"Recent articles and transcripts:\n{summaries}\n\n"
        f"Already-covered topics (avoid repeating):\n{past_block}\n\n"
        "Identify the single most novel tactical or strategic trend being tried by football "
        "players or teams. Something new that hasn't been widely adopted yet.\n\n"
        'Return JSON: {"trend": "<10-20 word description>", "reasoning": "<why this is novel>"}'
    )}])
    try:
        match = re.search(r"\{.*\}", resp.content[0].text, re.DOTALL)
        if match:
            return json.loads(match.group()).get("trend")
    except Exception:
        pass
    return None

# --- Report generation ---

def generate_report(conn, trend):
    qvec = oai.embeddings.create(model=EMBED_MODEL, input=[trend]).data[0].embedding
    vec_str = "[" + ",".join(str(v) for v in qvec) + "]"

    with conn.cursor() as cur:
        cur.execute(
            "SELECT c.id, c.source_id, c.content, s.title, s.url FROM chunks c "
            "JOIN sources s ON s.id = c.source_id ORDER BY c.embedding <=> %s::vector LIMIT 30",
            (vec_str,),
        )
        chunks = cur.fetchall()
    if not chunks:
        return None

    context = json.dumps([
        {"chunk_id": cid, "source_id": sid, "content": content, "source_title": title, "source_url": url}
        for cid, sid, content, title, url in chunks
    ], indent=2)

    resp = claude.messages.create(model=MODEL, max_tokens=12000, messages=[{"role": "user", "content": (
        f"You are a deep research analyst writing a comprehensive report on an emerging football trend.\n\n"
        f"Trend: {trend}\n\nSource evidence (JSON):\n{context}\n\n"
        "Write a deep research report in markdown structured as follows:\n\n"
        "# [Descriptive Title]\n\n"
        "## Executive Summary\nConcise overview of the trend and key findings.\n\n"
        "## Key Findings\nNumbered findings with evidence and inline citations [S<source_id>:C<chunk_id>].\n\n"
        "## Detailed Analysis\nDeep dive with subsections. **Bold** key statistics.\n\n"
        "## Evidence Assessment\nStrength of evidence and limitations.\n\n"
        "## Implications\nWhat this means for football tactics going forward.\n\n"
        "## Open Questions\nWhat remains unknown.\n\n"
        "## Sources\nList all cited sources with titles and URLs.\n\n"
        "Requirements:\n"
        "- Every claim must have an inline citation [S<source_id>:C<chunk_id>]\n"
        "- Bold key statistics and figures\n"
        "- Use tables for comparisons when useful\n"
        "- Be specific and evidence-grounded, flag any speculation"
    )}])

    report_md = resp.content[0].text
    with conn.cursor() as cur:
        cur.execute("INSERT INTO reports (title, content) VALUES (%s, %s)", (trend, report_md))
        conn.commit()

    slug = re.sub(r"[^a-z0-9]+", "-", trend.lower()).strip("-")[:60]
    out = ROOT / "reports" / f"{datetime.now().strftime('%Y-%m-%d')}-{slug}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(report_md)
    log.info("Report saved: %s", out)
    return report_md

# --- Main ---

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
