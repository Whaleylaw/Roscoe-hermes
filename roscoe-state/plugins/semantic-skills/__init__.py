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
  SEMANTIC_SKILLS_THRESHOLD=0.45     — minimum cosine similarity (default: 0.45)
  SEMANTIC_SKILLS_MAX_RESULTS=10     — max skills to surface (default: 10)
  SEMANTIC_SKILLS_MODEL=BAAI/bge-small-en-v1.5  — embedding model
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
THRESHOLD = float(os.environ.get("SEMANTIC_SKILLS_THRESHOLD", "0.55"))
MAX_RESULTS = int(os.environ.get("SEMANTIC_SKILLS_MAX_RESULTS", "8"))
MODEL_NAME = os.environ.get("SEMANTIC_SKILLS_MODEL", "BAAI/bge-small-en-v1.5")

# Persistent storage
DATA_DIR = Path(os.environ.get("SEMANTIC_SKILLS_DATA_DIR", "/opt/data/semantic-skills"))
INDEX_FILE = DATA_DIR / "skill_vectors.npz"
META_FILE = DATA_DIR / "skill_meta.json"
MANIFEST_FILE = DATA_DIR / "skill_manifest.json"

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
# Search
# ---------------------------------------------------------------------------

def search_skills(query: str) -> list:
    """Search skills by semantic similarity to query.
    
    Returns list of {name, description, category, score} above threshold,
    sorted by score descending, limited to MAX_RESULTS.
    """
    import numpy as np
    
    if _index is None or not _metadata:
        return []
    
    # Embed query
    q_vec = _embed([query])[0]
    
    # Cosine similarity (vectors are pre-normalized)
    scores = _index @ q_vec
    
    # Filter and sort
    results = []
    for i, score in enumerate(scores):
        if score >= THRESHOLD:
            results.append({
                "name": _metadata[i]["name"],
                "description": _metadata[i]["description"],
                "category": _metadata[i]["category"],
                "score": float(score),
            })
    
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:MAX_RESULTS]


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
