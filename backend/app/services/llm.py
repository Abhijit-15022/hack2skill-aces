"""Gemini wrapper. Every caller has an offline fallback, so the app still runs without a key.

Tiers: "lite" for quick yes/no calls, "fast" for high-volume summaries, "smart" for reasoning
(diagnosis, planning, meetings, SOP drafting). Each tier maps to a model and a thinking level.
"""
import contextvars
import hashlib
import json
import logging
import math
import re
import time
from functools import lru_cache
from typing import Any

from ..config import get_settings

log = logging.getLogger(__name__)
settings = get_settings()

# Set while seeding: embeddings are computed afterwards in batches instead of one call per row.
defer_embeddings = contextvars.ContextVar("defer_embeddings", default=False)


@lru_cache
def _client():
    if not enabled():
        return None
    from google import genai

    if settings.gemini_api_key:
        return genai.Client(api_key=settings.gemini_api_key)
    return genai.Client(vertexai=True, project=settings.google_cloud_project, location=settings.google_cloud_location)


def enabled() -> bool:
    return bool(settings.gemini_api_key or settings.google_cloud_project)


def _tier(tier: str) -> tuple[str, str | None]:
    if tier == "meeting":
        return settings.gemini_model_smart, settings.gemini_thinking_meeting
    if tier == "smart":
        return settings.gemini_model_smart, settings.gemini_thinking_smart
    if tier == "lite":
        return settings.gemini_model_lite, None
    return settings.gemini_model_fast, settings.gemini_thinking_fast


def model_names() -> dict:
    return {"smart": settings.gemini_model_smart, "fast": settings.gemini_model_fast,
            "lite": settings.gemini_model_lite, "embed": settings.gemini_embed_model} if enabled() else {}


def _call(fn, what: str, attempts: int = 4):
    """Retry rate limits and overloads with backoff; give up quietly so callers can fall back."""
    delay = 1.5
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:
            msg = str(exc)
            retryable = any(code in msg for code in ("429", "503", "500", "RESOURCE_EXHAUSTED", "UNAVAILABLE", "DEADLINE"))
            if not retryable or i == attempts - 1:
                log.warning("Gemini %s failed: %s", what, msg[:300])
                return None
            time.sleep(delay)
            delay *= 2
    return None


def _config(tier: str, system: str | None, json_out: bool, temperature: float):
    from google.genai import types

    model, thinking = _tier(tier)
    cfg = types.GenerateContentConfig(
        system_instruction=system,
        response_mime_type="application/json" if json_out else None,
        temperature=temperature,
        thinking_config=types.ThinkingConfig(thinking_level=thinking) if thinking else None,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    return model, cfg


def generate_json(prompt: str, tier: str = "fast", system: str | None = None, parts: list | None = None) -> dict | None:
    """Ask Gemini for a JSON object. `parts` may add files (e.g. uploaded audio) before the prompt."""
    client = _client()
    if client is None:
        return None
    model, cfg = _config(tier, system, True, 0.2)
    contents = [*(parts or []), prompt]
    resp = _call(lambda: client.models.generate_content(model=model, contents=contents, config=cfg), f"json/{tier}")
    return _parse_json(resp.text or "") if resp is not None else None


def generate_text(prompt: str, tier: str = "fast", system: str | None = None) -> str | None:
    client = _client()
    if client is None:
        return None
    model, cfg = _config(tier, system, False, 0.3)
    resp = _call(lambda: client.models.generate_content(model=model, contents=prompt, config=cfg), f"text/{tier}")
    return ((resp.text or "").strip() or None) if resp is not None else None


def upload_file(path: str, mime_type: str):
    """Upload a file (audio, PDF) for use as a prompt part. Returns None when Gemini is off."""
    client = _client()
    if client is None:
        return None
    from google.genai import types

    f = _call(lambda: client.files.upload(file=path, config=types.UploadFileConfig(mime_type=mime_type)), "upload")
    if f is None:
        return None
    for _ in range(60):  # audio is processed asynchronously
        state = getattr(getattr(f, "state", None), "name", "ACTIVE")
        if state != "PROCESSING":
            break
        time.sleep(1)
        f = client.files.get(name=f.name)
    return f


def _parse_json(raw: str) -> dict | None:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {"items": value}
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
    return None


_TOKEN = re.compile(r"[a-z0-9_]+")


def _hash_embed(text: str, dim: int) -> list[float]:
    """Offline fallback: hashed bag of words and bigrams. Good enough for lexical similarity."""
    vec = [0.0] * dim
    tokens = _TOKEN.findall((text or "").lower())
    grams = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]
    for g in grams:
        h = int(hashlib.md5(g.encode()).hexdigest(), 16)
        vec[h % dim] += 1.0 if (h >> 8) & 1 else -1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _normalise(vals) -> list[float]:
    vals = [float(v) for v in vals]
    norm = math.sqrt(sum(v * v for v in vals)) or 1.0
    return [v / norm for v in vals]


def embed(texts: list[str], task: str = "RETRIEVAL_DOCUMENT") -> list[list[float]] | None:
    """Embed in batches of 100. Returns None only when Gemini is on but failed, so callers never mix spaces."""
    dim = settings.embed_dim
    texts = [(t or " ")[:8000] for t in texts]
    client = _client()
    if client is None:
        return [_hash_embed(t, dim) for t in texts]
    from google.genai import types

    out: list[list[float]] = []
    for i in range(0, len(texts), 100):
        chunk = texts[i:i + 100]
        resp = _call(lambda: client.models.embed_content(
            model=settings.gemini_embed_model, contents=chunk,
            config=types.EmbedContentConfig(output_dimensionality=dim, task_type=task)), "embed")
        if resp is None or len(resp.embeddings) != len(chunk):
            return None
        out.extend(_normalise(e.values) for e in resp.embeddings)
    return out


def embed_one(text: str, task: str = "RETRIEVAL_DOCUMENT") -> list[float] | None:
    if defer_embeddings.get():
        return None
    result = embed([text], task)
    return result[0] if result else None


def cosine(a: Any, b: Any) -> float:
    if a is None or b is None:
        return 0.0
    a, b = [float(x) for x in a], [float(y) for y in b]
    num = sum(x * y for x, y in zip(a, b))
    da = math.sqrt(sum(x * x for x in a)) or 1.0
    db = math.sqrt(sum(y * y for y in b)) or 1.0
    return float(num / (da * db))
