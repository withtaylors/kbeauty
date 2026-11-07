"""
Product identification.

Two strategies share one interface:
  * `TextSearch`  — deterministic fuzzy match on brand / name (no network, always available)
  * `VisionIdentifier` — image → catalog id via an LLM with vision (OpenAI or Anthropic)

The model is only asked *which catalog item* is in the photo.  It never produces prices,
ingredients or advice — those come from the catalog and the engine.
"""
from __future__ import annotations

import base64
import binascii
import difflib
import json
import logging
import re
from dataclasses import dataclass
from typing import Protocol

import httpx

from .catalog import Catalog
from .config import Settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Identification:
    product_id: str | None
    confidence: float
    candidates: tuple[str, ...]
    method: str                 # "vision" | "vision_error" | "no_ai" | "search"
    seen_text: str = ""
    error: str | None = None


# ---------- text search ----------

_NON_WORD = re.compile(r"[^0-9a-z가-힣]+")


def _normalize(s: str) -> str:
    return _NON_WORD.sub(" ", (s or "").lower()).strip()


@dataclass(frozen=True)
class SearchHit:
    product_id: str
    score: float


class TextSearch:
    """Fuzzy search over brand + name in Korean and English.  Pure, deterministic."""

    def __init__(self, catalog: Catalog):
        self._index = {
            p.id: _normalize(" ".join([p.brand_en, p.brand_ko, p.name_en, p.name_ko, p.id.replace("-", " ")]))
            for p in catalog
        }

    def search(self, query: str, limit: int = 5, min_score: float = 0.2) -> list[SearchHit]:
        q = _normalize(query)
        if not q:
            return []
        q_tokens = set(q.split())
        hits: list[SearchHit] = []
        for pid, hay in self._index.items():
            h_tokens = set(hay.split())
            overlap = len(q_tokens & h_tokens) / len(q_tokens)
            partial = sum(1 for t in q_tokens if t in hay) / len(q_tokens)
            ratio = difflib.SequenceMatcher(None, q, hay).ratio()
            score = round(0.5 * partial + 0.35 * overlap + 0.15 * ratio, 3)
            if score > min_score:
                hits.append(SearchHit(pid, score))
        hits.sort(key=lambda h: (-h.score, h.product_id))
        return hits[:limit]

    def identify(self, query: str) -> Identification:
        hits = self.search(query)
        if not hits:
            return Identification(None, 0.0, (), "search")
        top = hits[0]
        decisive = top.score >= 0.8 and (len(hits) == 1 or top.score - hits[1].score >= 0.15)
        return Identification(top.product_id if decisive else None, top.score, tuple(h.product_id for h in hits), "search")


# ---------- vision ----------

class VisionProvider(Protocol):
    async def complete(self, prompt: str, image_b64: str, mime: str) -> str: ...


class OpenAIVision:
    def __init__(self, api_key: str, model: str, timeout: float):
        self._key, self._model, self._timeout = api_key, model, timeout

    async def complete(self, prompt: str, image_b64: str, mime: str) -> str:
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self._key}"},
                json={"model": self._model, "max_tokens": 300, "temperature": 0,
                      "messages": [{"role": "user", "content": [
                          {"type": "text", "text": prompt},
                          {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}", "detail": "high"}}]}]},
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]


class AnthropicVision:
    def __init__(self, api_key: str, model: str, timeout: float):
        self._key, self._model, self._timeout = api_key, model, timeout

    async def complete(self, prompt: str, image_b64: str, mime: str) -> str:
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": self._key, "anthropic-version": "2023-06-01"},
                json={"model": self._model, "max_tokens": 300,
                      "messages": [{"role": "user", "content": [
                          {"type": "image", "source": {"type": "base64", "media_type": mime, "data": image_b64}},
                          {"type": "text", "text": prompt}]}]},
            )
            r.raise_for_status()
            return r.json()["content"][0]["text"]


_PROMPT = """You identify K-beauty products from a shopper's photo taken in a Korean store.
Pick the product from the CATALOG that matches the photo. Read the brand and product text on the package (Korean or English).
Reply ONLY with JSON: {{"id": "<catalog id or null>", "confidence": 0.0-1.0, "candidates": ["<id>", "<id>", "<id>"], "seen_text": "<text you read>"}}
If the product is not in the catalog, set id to null and still list the 3 closest candidates.

CATALOG (id | English | Korean | size):
{catalog}"""

_DATA_URL = re.compile(r"^data:(image/[a-zA-Z0-9.+-]+);base64,(.+)$", re.S)
_JSON_BLOCK = re.compile(r"\{.*\}", re.S)


class InvalidImage(ValueError):
    pass


def decode_image(data_url_or_b64: str, max_bytes: int) -> tuple[str, str]:
    """Return (base64_payload, mime).  Validates size and base64 encoding."""
    m = _DATA_URL.match(data_url_or_b64.strip())
    payload, mime = (m.group(2), m.group(1)) if m else (data_url_or_b64.strip(), "image/jpeg")
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as e:
        raise InvalidImage("image is not valid base64") from e
    if not raw:
        raise InvalidImage("image is empty")
    if len(raw) > max_bytes:
        raise InvalidImage(f"image larger than {max_bytes // (1024*1024)} MB")
    return payload, mime


def _describe_error(e: httpx.HTTPError) -> str:
    """'429 insufficient_quota' style summary — never includes the key or the request body."""
    if isinstance(e, httpx.HTTPStatusError):
        code = ""
        try:
            err = e.response.json().get("error") or {}
            code = err.get("code") or err.get("type") or ""
        except ValueError:
            pass
        return f"{e.response.status_code} {code}".strip()
    return type(e).__name__


class VisionIdentifier:
    def __init__(self, provider: VisionProvider | None, catalog: Catalog):
        self._provider = provider
        self._catalog = catalog
        self._prompt = _PROMPT.format(catalog="\n".join(
            f"{p.id} | {p.brand_en} {p.name_en} | {p.brand_ko} {p.name_ko} | {p.size}" for p in catalog))

    @property
    def enabled(self) -> bool:
        return self._provider is not None

    async def identify(self, image_b64: str, mime: str) -> Identification:
        if self._provider is None:
            return Identification(None, 0.0, (), "no_ai", error="no_api_key")
        try:
            text = await self._provider.complete(self._prompt, image_b64, mime)
        except httpx.HTTPError as e:
            log.warning("vision provider failed: %s", e)
            return Identification(None, 0.0, (), "vision_error", error=_describe_error(e))
        return self._parse(text)

    def _parse(self, text: str) -> Identification:
        m = _JSON_BLOCK.search(text)
        try:
            out = json.loads(m.group(0)) if m else {}
        except json.JSONDecodeError:
            log.warning("vision returned non-JSON: %r", text[:200])
            out = {}
        pid = out.get("id") if out.get("id") in self._catalog else None
        cands = [c for c in (out.get("candidates") or []) if c in self._catalog]
        if pid and pid not in cands:
            cands.insert(0, pid)
        try:
            conf = max(0.0, min(1.0, float(out.get("confidence") or 0)))
        except (TypeError, ValueError):
            conf = 0.0
        return Identification(pid, conf, tuple(cands[:3]), "vision", seen_text=str(out.get("seen_text") or ""))


def build_vision(settings: Settings, catalog: Catalog) -> VisionIdentifier:
    provider: VisionProvider | None = None
    if settings.openai_api_key:
        provider = OpenAIVision(settings.openai_api_key, settings.openai_model, settings.vision_timeout_s)
    elif settings.anthropic_api_key:
        provider = AnthropicVision(settings.anthropic_api_key, settings.anthropic_model, settings.vision_timeout_s)
    return VisionIdentifier(provider, catalog)
