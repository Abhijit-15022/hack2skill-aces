"""Gemini wrapper. Every caller has an offline fallback, so the app runs before a key is configured."""
import hashlib
import json
import logging
import math
import re
from functools import lru_cache
from typing import Any

from ..config import get_settings

log = logging.getLogger(__name__)
settings = get_settings()


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


def _model(tier: str) -> str:
    return settings.gemini_model_smart if tier == "smart" else settings.gemini_model_fast


def generate_json(prompt: str, tier: str = "fast", system: str | None = None) -> dict | None:
    """Ask Gemini for a JSON object. Returns None when Gemini is off or the call fails."""
    client = _client()
    if client is None:
        return None
    from google.genai import types

    try:
        resp = client.models.generate_content(
            model=_model(tier),
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                temperature=0.2,
            ),
        )
        return _parse_json(resp.text or "")
    except Exception as exc:  # network, quota, safety block: fall back rather than fail the request
        log.warning("Gemini generate_json failed: %s", exc)
        return None


def generate_text(prompt: str, tier: str = "fast", system: str | None = None) -> str | None:
    client = _client()
    if client is None:
        return None
    from google.genai import types

    try:
        resp = client.models.generate_content(
            model=_model(tier),
            contents=prompt,
            config=types.GenerateContentConfig(system_instruction=system, temperature=0.3),
        )
        return (resp.text or "").strip() or None
    except Exception as exc:
        log.warning("Gemini generate_text failed: %s", exc)
        return None


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


def embed(texts: list[str], task: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
    dim = settings.embed_dim
    texts = [(t or "")[:8000] for t in texts]
    client = _client()
    if client is not None and texts:
        from google.genai import types

        try:
            resp = client.models.embed_content(
                model=settings.gemini_embed_model,
                contents=texts,
                config=types.EmbedContentConfig(output_dimensionality=dim, task_type=task),
            )
            out = []
            for e in resp.embeddings:
                vals = list(e.values)
                norm = math.sqrt(sum(v * v for v in vals)) or 1.0
                out.append([v / norm for v in vals])
            return out
        except Exception as exc:
            log.warning("Gemini embed failed, using offline embedding: %s", exc)
    return [_hash_embed(t, dim) for t in texts]


def embed_one(text: str, task: str = "RETRIEVAL_DOCUMENT") -> list[float]:
    return embed([text], task)[0]


def cosine(a: Any, b: Any) -> float:
    if a is None or b is None:
        return 0.0
    a, b = [float(x) for x in a], [float(y) for y in b]
    num = sum(x * y for x, y in zip(a, b))
    da = math.sqrt(sum(x * x for x in a)) or 1.0
    db = math.sqrt(sum(y * y for y in b)) or 1.0
    return float(num / (da * db))
