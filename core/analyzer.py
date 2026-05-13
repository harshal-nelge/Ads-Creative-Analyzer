from dotenv import load_dotenv
import os
import io
import json
import time
import base64
import logging
from pathlib import Path

from groq import Groq
from PIL import Image

from core.prompts import BREAKDOWN_SYSTEM_PROMPT, SCORING_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

load_dotenv()

# Paths
ROOT_DIR   = Path(__file__).parent.parent
ADS_DIR    = ROOT_DIR / "public" / "ads"
CACHE_PATH = ROOT_DIR / "cache.json"


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Image helpers ─────────────────────────────────────────────────────────────

def _encode_image_path(path: Path, max_px: int = 1024) -> str:
    """Load image from disk, resize, return base64 JPEG string."""
    img = Image.open(path).convert("RGB")
    img.thumbnail((max_px, max_px), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=82)
    return base64.b64encode(buf.getvalue()).decode()


def _encode_image_bytes(raw: bytes, max_px: int = 1024) -> str:
    """Load image from bytes (upload), resize, return base64 JPEG string."""
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    img.thumbnail((max_px, max_px), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=82)
    return base64.b64encode(buf.getvalue()).decode()


# ── Core analysis functions ───────────────────────────────────────────────────

def _call_breakdown(client: Groq, b64: str) -> dict:
    """Single Groq vision call → structured breakdown dict."""
    response = client.chat.completions.create(
        model="llama-3.2-90b-vision-preview",
        response_format={"type": "json_object"},
        max_tokens=800,
        messages=[
            {"role": "system", "content": BREAKDOWN_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                    },
                    {"type": "text", "text": "Analyze this ad creative. Return JSON only."},
                ],
            },
        ],
    )
    return json.loads(response.choices[0].message.content)


def _call_scoring(client: Groq, breakdowns: list[dict]) -> dict:
    """Single Groq text call → scores + pattern analysis + ideas."""
    # Strip image_b64 from payload to save tokens
    clean = [
        {k: v for k, v in bd.items() if k not in ("image_b64", "image_path")}
        for bd in breakdowns
    ]
    payload = json.dumps(clean, indent=2, ensure_ascii=False)

    response = client.chat.completions.create(
        model="llama-3.2-90b-vision-preview",
        response_format={"type": "json_object"},
        max_tokens=2000,
        messages=[
            {"role": "system", "content": SCORING_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Here are the structured breakdowns for all ads:\n\n{payload}",
            },
        ],
    )
    return json.loads(response.choices[0].message.content)


# ── Public API ────────────────────────────────────────────────────────────────

def load_ads_from_disk() -> list[dict]:
    """
    Scan ADS_DIR for images.
    Returns list of {id, filename, image_b64, image_path (URL for frontend)}.
    """
    ads = []
    for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
        for f in sorted(ADS_DIR.glob(ext)):
            ads.append({
                "id":         f.stem,
                "filename":   f.name,
                "image_b64":  _encode_image_path(f),
                "image_path": f"/ads/{f.name}",   # served by Vercel CDN / local StaticFiles
            })
    if not ads:
        raise FileNotFoundError(
            f"No images found in {ADS_DIR}. "
            "Add PNG/JPG screenshots of ads to public/ads/ and rebuild the cache."
        )
    return ads


def run_pipeline(force_refresh: bool = False) -> dict:
    """
    Full pipeline using images committed to public/ads/.
    Reads/writes cache.json — run this LOCALLY before deploying.

    Returns: {breakdowns, report}
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise EnvironmentError("GROQ_API_KEY not set. Export it before running.")

    client = Groq(api_key=api_key)
    ads    = load_ads_from_disk()
    cache  = {} if force_refresh else _load_cache()

    breakdowns = []
    for i, ad in enumerate(ads):
        if ad["id"] in cache:
            logger.info(f"[{i+1}/{len(ads)}] Cache hit: {ad['id']}")
            breakdowns.append(cache[ad["id"]])
        else:
            logger.info(f"[{i+1}/{len(ads)}] Analyzing: {ad['id']}")
            bd = _call_breakdown(client, ad["image_b64"])
            bd["ad_id"]      = ad["id"]
            bd["filename"]   = ad["filename"]
            bd["image_path"] = ad["image_path"]
            cache[ad["id"]] = bd
            _save_cache(cache)          # save after each — safe against crashes
            breakdowns.append(bd)
            if i < len(ads) - 1:
                time.sleep(2)           # Groq rate limit: ~30 req/min on vision

    report = _call_scoring(client, breakdowns)

    # Persist report inside cache so Vercel can serve it without calling Groq
    cache["__report__"] = report
    _save_cache(cache)

    return {"breakdowns": breakdowns, "report": report}


def run_pipeline_from_uploads(image_files: list[tuple[str, bytes]]) -> dict:
    """
    Full pipeline on uploaded image bytes (no disk required).
    Used by the /api/upload-and-analyze endpoint.

    Args:
        image_files: list of (filename, raw_bytes)

    Returns: {breakdowns, report}
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "GROQ_API_KEY is not set on the server. "
            "Add it in Vercel → Project → Settings → Environment Variables."
        )

    client     = Groq(api_key=api_key)
    breakdowns = []

    for i, (filename, raw) in enumerate(image_files):
        logger.info(f"[{i+1}/{len(image_files)}] Analyzing upload: {filename}")
        b64 = _encode_image_bytes(raw)
        bd  = _call_breakdown(client, b64)

        stem              = Path(filename).stem
        bd["ad_id"]       = stem
        bd["filename"]    = filename
        bd["image_b64"]   = b64       # returned to frontend for inline display
        bd["image_path"]  = None      # no static URL for uploads

        breakdowns.append(bd)
        if i < len(image_files) - 1:
            time.sleep(2)

    report = _call_scoring(client, breakdowns)
    return {"breakdowns": breakdowns, "report": report}


def build_response_from_cache() -> dict:
    """
    Reconstruct a full response from cache.json without any API call.
    Used by GET /api/analyze on the deployed Vercel instance.
    """
    cache      = _load_cache()
    report     = cache.get("__report__", {
        "scored_ads":       [],
        "top_performers":   [],
        "bottom_performers": [],
        "pattern_analysis": "Cache found but no report — re-run the pipeline locally.",
        "creative_ideas":   [],
    })
    breakdowns = [v for k, v in cache.items() if k != "__report__"]
    return {"breakdowns": breakdowns, "report": report}