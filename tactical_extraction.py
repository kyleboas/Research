"""Football-aware tactical pattern extraction.

Extracts structured tactical patterns from article text:
  actor (role/player/team) → action (tactical behavior) → context (zone/phase/shape)

This gives the detection layer football-specific signals beyond generic topic
clustering. A weak trend often looks like a structured relation — "fullback
inverts in buildup", "winger rotates into half-space" — not just a topic.
"""

import json
import logging
import re
from collections import defaultdict

log = logging.getLogger("research")

# ── Football vocabulary for pattern recognition ──────────────────────────────

ROLES = {
    "goalkeeper", "keeper", "gk",
    "centre-back", "center-back", "centre back", "center back", "cb",
    "full-back", "fullback", "full back", "left-back", "right-back",
    "left back", "right back", "lb", "rb", "wing-back", "wingback", "wb",
    "defensive midfielder", "holding midfielder", "cdm", "dm", "pivot",
    "central midfielder", "cm", "box-to-box",
    "attacking midfielder", "cam", "no. 10", "number 10", "playmaker",
    "winger", "wide player", "lw", "rw", "inside forward",
    "striker", "centre-forward", "center-forward", "cf", "no. 9", "number 9",
    "false 9", "false nine", "target man",
}

TACTICAL_ACTIONS = {
    "invert", "inverted", "inverting", "inversion",
    "rotate", "rotated", "rotating", "rotation",
    "overlap", "overlapping", "underlap", "underlapping",
    "press", "pressing", "counter-press", "gegenpressing",
    "drop", "dropping", "deep", "deepening",
    "tuck", "tucking", "tucked",
    "switch", "switching", "overload", "overloading",
    "build-up", "buildup", "build up", "progression",
    "transition", "transitioning", "counter-attack", "counterattack",
    "man-mark", "man-marking", "zonal", "cover shadow",
    "high line", "high block", "low block", "mid block",
    "half-space", "halfspace", "half space",
    "double pivot", "single pivot", "regista",
    "box overload", "positional play", "juego de posición",
    "back three", "back four", "back five",
    "asymmetric", "asymmetrical", "hybrid",
}

ZONES = {
    "half-space", "halfspace", "half space",
    "wide area", "wide zone", "flank",
    "channel", "inside channel",
    "box", "penalty area", "18-yard",
    "final third", "middle third", "defensive third",
    "left side", "right side", "central", "centrally",
    "between the lines", "pocket", "zone 14",
    "near post", "far post", "six-yard",
    "touchline", "byline", "deep",
    "high", "low", "midfield",
}

PHASES = {
    "in possession", "out of possession",
    "build-up", "buildup", "build up",
    "attacking transition", "defensive transition",
    "pressing", "counter-pressing",
    "set piece", "set-piece", "corner", "free kick",
    "goal kick", "throw-in",
    "rest defence", "rest defense",
    "final third attack", "chance creation",
}

FORMATIONS = re.compile(
    r"\b(\d-\d-\d(?:-\d)?)\b"
    r"|"
    r"\b(4-4-2|4-3-3|3-5-2|4-2-3-1|3-4-3|4-1-4-1|5-3-2|5-4-1|4-3-2-1|3-4-2-1|4-2-4-0|4-1-2-1-2)\b",
    re.IGNORECASE,
)


def _normalize(text):
    return text.lower().strip()


def _find_matches(text, vocab_set):
    """Find all vocabulary terms present in text."""
    text_lower = text.lower()
    found = []
    for term in vocab_set:
        if term in text_lower:
            found.append(term)
    return found


def extract_tactical_context(text):
    """Extract football-specific metadata from a text chunk.

    Returns a dict with:
        roles: list of player roles mentioned
        actions: list of tactical actions mentioned
        zones: list of pitch zones mentioned
        phases: list of game phases mentioned
        formations: list of formations mentioned
        teams: list of likely team names (capitalized multi-word sequences)
        tactical_density: float 0-1 indicating how tactically rich the chunk is
    """
    roles = _find_matches(text, ROLES)
    actions = _find_matches(text, TACTICAL_ACTIONS)
    zones = _find_matches(text, ZONES)
    phases = _find_matches(text, PHASES)
    formations = FORMATIONS.findall(text)
    formations = [f[0] or f[1] for f in formations if f[0] or f[1]]

    # Estimate tactical density: how rich is this chunk in football tactics content?
    total_terms = len(roles) + len(actions) + len(zones) + len(phases) + len(formations)
    word_count = max(1, len(text.split()))
    tactical_density = min(1.0, total_terms / (word_count * 0.05))  # normalize: 5% tactical terms = 1.0

    return {
        "roles": list(set(roles)),
        "actions": list(set(actions)),
        "zones": list(set(zones)),
        "phases": list(set(phases)),
        "formations": formations,
        "tactical_density": round(tactical_density, 3),
    }


def extract_tactical_patterns(text, source_id=None, chunk_id=None):
    """Extract structured tactical patterns (actor → action → context) from text.

    Looks for sentences that contain both a role/actor AND a tactical action,
    then builds a structured pattern record. These patterns are the football-specific
    signals that complement generic topic clustering.

    Returns list of pattern dicts ready for DB insertion.
    """
    patterns = []
    sentences = re.split(r'[.!?]\s+', text)

    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence) < 20:
            continue

        roles = _find_matches(sentence, ROLES)
        actions = _find_matches(sentence, TACTICAL_ACTIONS)
        zones = _find_matches(sentence, ZONES)
        phases = _find_matches(sentence, PHASES)

        # Only create a pattern when we have both an actor and an action
        if not roles or not actions:
            continue

        # Build the pattern: first role found + first action found
        for role in roles[:2]:  # cap at 2 roles per sentence
            for action in actions[:2]:  # cap at 2 actions per sentence
                pattern = {
                    "source_id": source_id,
                    "chunk_id": chunk_id,
                    "pattern_type": "role_action",
                    "actor": role,
                    "action": action,
                    "context": sentence[:300],
                    "zones": zones[:3],
                    "phase": phases[0] if phases else None,
                }
                patterns.append(pattern)

    return patterns


def chunk_with_context(text, chunk_size=200, stride=160):
    """Football-aware chunking that preserves tactical context.

    Improvements over naive word-count slicing:
    1. Tries to break at sentence boundaries when possible
    2. Preserves paragraph structure for tactical descriptions
    3. Attaches tactical metadata to each chunk
    4. Scores chunks by tactical density so detection can prioritize them

    Returns list of dicts: [{content, chunk_index, tactical_context}, ...]
    """
    if not text or not text.strip():
        return []

    # Split into paragraphs first, then sentences within paragraphs
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [text]

    # Build sentence-level units
    sentences = []
    for para in paragraphs:
        para_sentences = re.split(r'(?<=[.!?])\s+', para)
        for s in para_sentences:
            s = s.strip()
            if s:
                sentences.append(s)
        sentences.append("")  # paragraph break marker

    # Build chunks respecting sentence boundaries
    chunks = []
    current_words = []
    current_sentences = []

    for sentence in sentences:
        words = sentence.split()

        # If adding this sentence exceeds chunk_size, finalize current chunk
        if current_words and len(current_words) + len(words) > chunk_size:
            chunk_text = " ".join(current_words)
            if chunk_text.strip():
                ctx = extract_tactical_context(chunk_text)
                chunks.append({
                    "content": chunk_text.strip(),
                    "chunk_index": len(chunks),
                    "tactical_context": ctx,
                })

            # Keep overlap: take last few sentences that fit in stride words
            overlap_words = []
            for s in reversed(current_sentences):
                s_words = s.split()
                if len(overlap_words) + len(s_words) > (chunk_size - stride):
                    break
                overlap_words = s_words + overlap_words
            current_words = overlap_words
            current_sentences = []

        current_words.extend(words)
        if sentence:  # skip empty paragraph markers
            current_sentences.append(sentence)

    # Final chunk
    if current_words:
        chunk_text = " ".join(current_words)
        if chunk_text.strip():
            ctx = extract_tactical_context(chunk_text)
            chunks.append({
                "content": chunk_text.strip(),
                "chunk_index": len(chunks),
                "tactical_context": ctx,
            })

    # Fallback: if sentence-based chunking produced nothing (e.g., no punctuation),
    # use word-level chunking like the original
    if not chunks:
        words = text.split()
        for i in range(0, len(words), stride):
            chunk_text = " ".join(words[i:i + chunk_size])
            if chunk_text.strip():
                ctx = extract_tactical_context(chunk_text)
                chunks.append({
                    "content": chunk_text.strip(),
                    "chunk_index": len(chunks),
                    "tactical_context": ctx,
                })
            if i + chunk_size >= len(words):
                break

    return chunks
