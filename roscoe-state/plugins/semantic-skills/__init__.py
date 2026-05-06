"""
Semantic Skills Plugin for Hermes
=================================

Replaces the static 2000+ token skill index in the system prompt with
on-demand semantic search. Only skills relevant to the current user
message are surfaced each turn.

Architecture:
  1. On register(), build or load a vector index of all skill descriptions
  2. On each pre_llm_call, embed the user message and cosine-search
  3. Return matching skills as context injected into the user message

Dependencies:
  - fastembed (BAAI/bge-small-en-v1.5, ~42MB ONNX model)
  - numpy (comes with fastembed)

Config (env vars):
  SEMANTIC_SKILLS_ENABLED=true       — master toggle (default: true)
  SEMANTIC_SKILLS_THRESHOLD=0.60     — minimum cosine similarity (default: 0.60)
  SEMANTIC_SKILLS_MAX_RESULTS=4      — max skills to surface (default: 4)
  SEMANTIC_SKILLS_MODEL=BAAI/bge-small-en-v1.5  — embedding model

Relevance tuning:
  - low-signal acknowledgements/status nudges return no matches;
  - explicit skill/plugin/hook/filter queries only surface skill-system skills;
  - normal task queries need lexical support or a very strong vector score;
  - weak tail matches are trimmed so only tight result clusters are injected.
"""

import logging
import os
import json
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ENABLED = os.environ.get("SEMANTIC_SKILLS_ENABLED", "true").lower() in ("true", "1", "yes")
THRESHOLD = float(os.environ.get("SEMANTIC_SKILLS_THRESHOLD", "0.60"))
MAX_RESULTS = int(os.environ.get("SEMANTIC_SKILLS_MAX_RESULTS", "4"))
MODEL_NAME = os.environ.get("SEMANTIC_SKILLS_MODEL", "BAAI/bge-small-en-v1.5")

_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "can", "do", "for", "from",
    "have", "how", "i", "if", "in", "is", "it", "its", "just", "let", "me", "my", "of",
    "on", "or", "our", "so", "that", "the", "this", "to", "up", "we", "what", "when",
    "where", "which", "who", "why", "with", "you", "your",
}

_SKILL_INTENT_TERMS = {"skill", "skills", "plugin", "plugins", "hook", "hooks", "filter", "marketplace"}
_GENERIC_LOW_SIGNAL_TERMS = {"break", "broke", "broken", "done", "happen", "happened", "ok", "okay", "yes", "no"}

# Persistent storage
DATA_DIR = Path(os.environ.get("SEMANTIC_SKILLS_DATA_DIR", "/opt/data/semantic-skills"))
INDEX_FILE = DATA_DIR / "skill_vectors.npz"
META_FILE = DATA_DIR / "skill_meta.json"
MANIFEST_FILE = DATA_DIR / "skill_manifest.json"
STATS_FILE = Path(os.environ.get(
    "SKILL_LIBRARY_STATS_FILE",
    str(Path.home() / ".hermes" / "skill-library" / "stats" / "skill_usage.json"),
))

# Singleton state
_model = None
_index = None       # numpy array (N, 384)
_metadata = None    # list of dicts: {name, description, category}
_initialized = False


# ---------------------------------------------------------------------------
# Embedding model (lazy-loaded singleton)
# ---------------------------------------------------------------------------

def _get_model():
    """Lazy-load the embedding model. ~1s first call, instant after."""
    global _model
    if _model is None:
        try:
            from fastembed import TextEmbedding
            logger.info("Loading embedding model: %s", MODEL_NAME)
            start = time.perf_counter()
            _model = TextEmbedding(model_name=MODEL_NAME)
            elapsed = time.perf_counter() - start
            logger.info("Embedding model loaded in %.2fs", elapsed)
        except ImportError:
            logger.error("fastembed not installed. Run: pip install fastembed")
            raise
    return _model


def _embed(texts: list) -> "np.ndarray":
    """Embed a list of texts. Returns (N, dim) numpy array."""
    import numpy as np
    model = _get_model()
    embeddings = list(model.embed(texts))
    arr = np.array(embeddings, dtype=np.float32)
    # Normalize for cosine similarity
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1  # avoid division by zero
    return arr / norms


# ---------------------------------------------------------------------------
# Skill scanning — reads the same SKILL.md files as prompt_builder
# ---------------------------------------------------------------------------

def _scan_skills() -> list:
    """Scan all skill directories and extract name + description.
    
    Returns list of {name, description, category, path, mtime, size}.
    """
    from hermes_constants import get_hermes_home
    
    skills_dir = get_hermes_home() / "skills"
    if not skills_dir.exists():
        return []
    
    skills = []
    for skill_file in sorted(skills_dir.rglob("SKILL.md")):
        try:
            content = skill_file.read_text(encoding="utf-8")
            
            # Parse YAML frontmatter
            name, description, category = _parse_frontmatter(content, skill_file, skills_dir)
            if not name or not description:
                continue
            
            stat = skill_file.stat()
            skills.append({
                "name": name,
                "description": description,
                "category": category,
                "path": str(skill_file),
                "mtime": stat.st_mtime,
                "size": stat.st_size,
            })
        except Exception as e:
            logger.debug("Could not parse %s: %s", skill_file, e)
    
    return skills


def _parse_frontmatter(content: str, skill_file: Path, skills_dir: Path) -> tuple:
    """Extract name, description, category from SKILL.md frontmatter."""
    name = ""
    description = ""
    
    if content.startswith("---"):
        end = content.find("---", 3)
        if end > 0:
            fm_text = content[3:end]
            try:
                import yaml
                fm = yaml.safe_load(fm_text) or {}
                name = fm.get("name", "")
                description = fm.get("description", "")
            except Exception:
                # Fallback: regex parse
                import re
                m = re.search(r'name:\s*["\']?(.+?)["\']?\s*$', fm_text, re.MULTILINE)
                if m:
                    name = m.group(1).strip()
                m = re.search(r'description:\s*["\']?(.+?)(?:["\']?\s*$)', fm_text, re.MULTILINE)
                if m:
                    description = m.group(1).strip()
    
    # Derive name from path if not in frontmatter
    if not name:
        rel = skill_file.relative_to(skills_dir)
        parts = list(rel.parts[:-1])  # drop SKILL.md
        name = parts[-1] if parts else skill_file.parent.name
    
    # Derive category from directory structure
    rel = skill_file.relative_to(skills_dir)
    parts = list(rel.parts)
    if len(parts) > 2:
        category = "/".join(parts[:-2])  # e.g., "mlops/training"
    elif len(parts) > 1:
        category = parts[0]  # e.g., "devops"
    else:
        category = "general"
    
    # Clean up description — remove quotes, strip
    if isinstance(description, str):
        description = description.strip().strip("'\"").strip()
    
    return name, description, category


# ---------------------------------------------------------------------------
# Index management — build, save, load, check freshness
# ---------------------------------------------------------------------------

def _build_manifest(skills: list) -> dict:
    """Build a manifest for cache validation (mtime+size per skill)."""
    return {
        s["name"]: {"mtime": s["mtime"], "size": s["size"]}
        for s in skills
    }


def _is_index_fresh(skills: list) -> bool:
    """Check if the saved index is still valid (no skills added/removed/modified)."""
    if not MANIFEST_FILE.exists() or not INDEX_FILE.exists() or not META_FILE.exists():
        return False
    
    try:
        with open(MANIFEST_FILE) as f:
            saved_manifest = json.load(f)
        current_manifest = _build_manifest(skills)
        return saved_manifest == current_manifest
    except Exception:
        return False


def _save_index(vectors, metadata, skills):
    """Persist the vector index and metadata to disk."""
    import numpy as np
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    np.savez(INDEX_FILE, vectors=vectors)
    with open(META_FILE, "w") as f:
        json.dump(metadata, f)
    with open(MANIFEST_FILE, "w") as f:
        json.dump(_build_manifest(skills), f)
    logger.info("Saved skill index: %d skills, %d bytes", len(metadata), INDEX_FILE.stat().st_size)


def _load_index():
    """Load persisted index from disk. Returns (vectors, metadata) or (None, None)."""
    import numpy as np
    try:
        data = np.load(INDEX_FILE)
        vectors = data["vectors"]
        with open(META_FILE) as f:
            metadata = json.load(f)
        if len(vectors) != len(metadata):
            logger.warning("Index/metadata length mismatch, rebuilding")
            return None, None
        return vectors, metadata
    except Exception as e:
        logger.warning("Could not load index: %s", e)
        return None, None


def _build_or_load_index():
    """Build the vector index (or load from cache if fresh)."""
    global _index, _metadata
    
    start = time.perf_counter()
    skills = _scan_skills()
    
    if not skills:
        logger.warning("No skills found to index")
        _index = None
        _metadata = []
        return
    
    # Check if cached index is still valid
    if _is_index_fresh(skills):
        vectors, metadata = _load_index()
        if vectors is not None:
            _index = vectors
            _metadata = metadata
            elapsed = time.perf_counter() - start
            logger.info("Loaded cached skill index: %d skills in %.3fs", len(metadata), elapsed)
            return
    
    # Build new index
    logger.info("Building skill index for %d skills...", len(skills))
    
    # Embed: use "skill_name: description" as the text for each skill
    texts = [f"{s['name']}: {s['description']}" for s in skills]
    vectors = _embed(texts)
    
    metadata = [
        {"name": s["name"], "description": s["description"], "category": s["category"]}
        for s in skills
    ]
    
    _save_index(vectors, metadata, skills)
    _index = vectors
    _metadata = metadata
    
    elapsed = time.perf_counter() - start
    logger.info("Built skill index: %d skills in %.2fs", len(skills), elapsed)


# ---------------------------------------------------------------------------
# Search / telemetry
# ---------------------------------------------------------------------------

def _record_surfaced(results: list, session_id: str = "", platform: str = "") -> None:
    """Track how often each skill is surfaced by semantic search.

    Best-effort only: telemetry failure must never block prompt assembly.
    """
    if not results:
        return
    try:
        import fcntl

        STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
        lock_path = STATS_FILE.with_suffix(STATS_FILE.suffix + ".lock")
        with lock_path.open("a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                data = json.loads(STATS_FILE.read_text(encoding="utf-8")) if STATS_FILE.exists() else {}
            except Exception:
                data = {}
            skills = data.setdefault("skills", {})
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            for result in results:
                name = str(result.get("name") or "").strip()
                if not name:
                    continue
                rec = skills.setdefault(name, {})
                rec["surfaced_count"] = int(rec.get("surfaced_count", 0)) + 1
                rec["last_surfaced_at"] = now
                rec["last_surfaced_score"] = float(result.get("score", 0.0))
                rec["last_surfaced_category"] = result.get("category", "")
                if session_id:
                    rec["last_surfaced_session"] = session_id
                if platform:
                    rec["last_surfaced_platform"] = platform
            data["updatedAt"] = now
            tmp = STATS_FILE.with_suffix(STATS_FILE.suffix + ".tmp")
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            tmp.replace(STATS_FILE)
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    except Exception:
        logger.debug("Could not record semantic skill telemetry", exc_info=True)


def _tokens(text: str) -> set:
    """Return meaningful lowercase tokens for lightweight lexical guards."""
    import re

    return {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9_-]{1,}", text.lower())
        if token not in _STOPWORDS
    }


def _is_low_signal_query(query_tokens: set) -> bool:
    """Avoid surfacing random skills for acknowledgements/status nudges."""
    if not query_tokens:
        return True
    if query_tokens <= _GENERIC_LOW_SIGNAL_TERMS:
        return True
    return len(query_tokens) < 3 and not (query_tokens & _SKILL_INTENT_TERMS)


def search_skills(query: str) -> list:
    """Search skills by semantic similarity to query.
    
    Returns list of {name, description, category, score} above threshold,
    sorted by score descending, limited to MAX_RESULTS.
    """
    import numpy as np
    
    if _index is None or not _metadata:
        return []

    query_tokens = _tokens(query)
    if _is_low_signal_query(query_tokens):
        return []
    skill_intent = bool(query_tokens & _SKILL_INTENT_TERMS)
    
    # Embed query
    q_vec = _embed([query])[0]
    
    # Cosine similarity (vectors are pre-normalized)
    scores = _index @ q_vec
    
    min_score = max(THRESHOLD, 0.60)

    # Filter and sort. The embedding score finds candidates; lexical overlap
    # prevents generic semantically-adjacent skills from surfacing on vague turns.
    candidates = []
    for i, score in enumerate(scores):
        if score < min_score:
            continue

        metadata = _metadata[i]
        searchable = f"{metadata['name']} {metadata['description']} {metadata['category']}"
        skill_tokens = _tokens(searchable)
        overlap = query_tokens & skill_tokens
        intent_overlap = skill_tokens & _SKILL_INTENT_TERMS

        # If the user is explicitly talking about skills/plugins/hooks, keep
        # candidates that are themselves about the skill system or marketplace.
        # This blocks unrelated "search" matches like Obsidian notes.
        if skill_intent and not intent_overlap:
            continue

        # For normal turns, require either direct lexical support or a strong
        # vector score. This keeps recall for clear task matches while dropping
        # random matches from vague status messages.
        if not skill_intent and len(overlap) < 2 and score < (min_score + 0.08):
            continue

        lexical_bonus = min(0.06, 0.015 * len(overlap))
        name_bonus = 0.04 if query_tokens & _tokens(metadata["name"]) else 0.0
        adjusted_score = float(score + lexical_bonus + name_bonus)
        candidates.append({
            "name": metadata["name"],
            "description": metadata["description"],
            "category": metadata["category"],
            "score": float(score),
            "adjusted_score": adjusted_score,
        })
    
    candidates.sort(key=lambda x: x["adjusted_score"], reverse=True)

    # Keep tight clusters only. If the top match is substantially better, don't
    # drag in weak tail matches just because they crossed the raw threshold.
    if candidates:
        top = candidates[0]["adjusted_score"]
        candidates = [r for r in candidates if r["adjusted_score"] >= top - 0.05]

    results = []
    for result in candidates[:MAX_RESULTS]:
        result.pop("adjusted_score", None)
        results.append(result)
    return results


# ---------------------------------------------------------------------------
# Hook: pre_llm_call
# ---------------------------------------------------------------------------

def _on_pre_llm_call(
    session_id: str = "",
    user_message: str = "",
    conversation_history: list = None,
    is_first_turn: bool = False,
    model: str = "",
    platform: str = "",
    **kwargs,
) -> dict:
    """Called before each LLM turn. Returns relevant skills as context."""
    global _initialized
    
    if not ENABLED:
        return {}
    
    if not user_message or not user_message.strip():
        return {}
    
    # Lazy-init the index on first call (not at import time)
    if not _initialized:
        try:
            _build_or_load_index()
            _initialized = True
        except Exception as e:
            logger.error("Failed to initialize skill index: %s", e)
            _initialized = True  # don't retry every turn
            return {}
    
    try:
        start = time.perf_counter()
        results = search_skills(user_message)
        elapsed = time.perf_counter() - start
        
        if not results:
            logger.debug("Semantic skills: no matches for query (%.1fms)", elapsed * 1000)
            return {}
        
        _record_surfaced(results, session_id=session_id, platform=platform)

        # Format results for injection
        lines = ["[Semantic skill matches for this message:]"]
        for r in results:
            lines.append(f"  - {r['name']} ({r['category']}): {r['description']} [score: {r['score']:.2f}]")
        lines.append("")
        lines.append("To use a skill, call skill_view(name) to load its full instructions.")
        
        context = "\n".join(lines)
        
        logger.info(
            "Semantic skills: %d matches in %.1fms (top: %s @ %.2f)",
            len(results), elapsed * 1000,
            results[0]["name"], results[0]["score"],
        )
        
        return {"context": context}
    
    except Exception as e:
        logger.warning("Semantic skills search failed: %s", e)
        return {}


# ---------------------------------------------------------------------------
# Plugin registration
# ---------------------------------------------------------------------------

def register(ctx):
    """Called by Hermes plugin system on startup."""
    if not ENABLED:
        logger.info("Semantic skills plugin disabled (SEMANTIC_SKILLS_ENABLED != true)")
        return
    
    ctx.register_hook("pre_llm_call", _on_pre_llm_call)
    
    # Set env flag so prompt_builder can skip the static index
    os.environ["HERMES_SEMANTIC_SKILLS_ACTIVE"] = "true"
    
    logger.info("Semantic skills plugin registered (threshold=%.2f, max=%d)", THRESHOLD, MAX_RESULTS)
