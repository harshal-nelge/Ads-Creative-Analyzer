import os
import sys
from pathlib import Path

# Make core/ importable regardless of working directory
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, HTTPException, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from typing import List

from core.analyzer import (
    run_pipeline_from_uploads,
    build_response_from_cache,
    _load_cache,
    ADS_DIR,
)

# ── App setup ─────────────────────────────────────────────────────────────────

app = FastAPI(title="Ads Creative Analyzer")

@app.get("/favicon.ico", include_in_schema=False)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

PUBLIC_DIR = Path(__file__).parent.parent / "public"

# Mount static files for Render (and local dev)
# Vercel auto-serves public/ads/ from CDN, so this mount is only used on Render
if (PUBLIC_DIR / "ads").exists():
    app.mount("/ads", StaticFiles(directory=str(PUBLIC_DIR / "ads")), name="ads")


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    """Serve the frontend SPA."""
    html = PUBLIC_DIR / "index.html"
    if not html.exists():
        raise HTTPException(status_code=404, detail="index.html not found in public/")
    return FileResponse(str(html))


@app.get("/health")
async def health():
    """
    Lightweight health check endpoint to prevent Render free tier shutdown.
    Ping this every 2-3 minutes to keep the dyno awake.
    """
    return {"status": "ok"}


@app.get("/api/status")
async def status():
    """
    Quick health-check.
    Returns how many ads are on disk and how many breakdowns are cached.
    """
    cache = _load_cache()
    ads   = (
        list(ADS_DIR.glob("*.png"))
        + list(ADS_DIR.glob("*.jpg"))
        + list(ADS_DIR.glob("*.jpeg"))
        + list(ADS_DIR.glob("*.webp"))
    )
    cached_count = len([k for k in cache if k != "__report__"])
    return {
        "ads_on_disk":          len(ads),
        "cached_breakdowns":    cached_count,
        "has_report":           "__report__" in cache,
        "ready":                cached_count > 0,
        "groq_key_set":         bool(os.environ.get("GROQ_API_KEY")),
    }


@app.get("/api/analyze")
async def get_demo_analysis():
    """
    Return the pre-built analysis from cache.json (demo brand).
    No Groq API call — instant response.
    Build the cache locally with: python -c "from core.analyzer import run_pipeline; run_pipeline()"
    """
    cache = _load_cache()
    if not cache:
        raise HTTPException(
            status_code=404,
            detail=(
                "cache.json is empty or missing. "
                "Run the pipeline locally first: "
                "python -c \"from core.analyzer import run_pipeline; run_pipeline()\""
            ),
        )
    return build_response_from_cache()


@app.post("/api/upload-and-analyze")
async def upload_and_analyze(files: List[UploadFile] = File(...)):
    """
    Accept 2–15 ad image uploads from the tester.
    Runs live Groq vision analysis on each image (in-memory, no disk write).
    Requires GROQ_API_KEY to be set as an environment variable.

    Returns the same shape as GET /api/analyze:
      { breakdowns: [...], report: {...} }
    where each breakdown includes image_b64 for inline frontend display.
    """
    # ── Validation ────────────────────────────────────────────
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")

    if len(files) < 2:
        raise HTTPException(status_code=400, detail="Upload at least 2 images.")

    if len(files) > 15:
        raise HTTPException(status_code=400, detail="Maximum 15 images per analysis.")

    allowed_types = {"image/png", "image/jpeg", "image/jpg", "image/webp"}
    image_files   = []

    for f in files:
        if f.content_type not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail=f"'{f.filename}' is not a supported image type (PNG / JPG / WEBP only).",
            )
        contents = await f.read()
        if len(contents) > 10 * 1024 * 1024:          # 10 MB per image
            raise HTTPException(
                status_code=400,
                detail=f"'{f.filename}' exceeds the 10 MB size limit.",
            )
        image_files.append((f.filename, contents))

    # ── Run pipeline ──────────────────────────────────────────
    try:
        result = run_pipeline_from_uploads(image_files)
        return result
    except EnvironmentError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {e}")