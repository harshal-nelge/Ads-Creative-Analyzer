# Ads Creative Analyzer

An AI-powered ad creative analysis tool that uses computer vision to break down and score advertising creatives. Built with FastAPI backend and modern SPA frontend.

## Description

**Ads Creative Analyzer** helps marketers and agencies understand the composition, messaging, and effectiveness of their ad creatives through AI-driven visual analysis. Simply upload 2-15 ad images and get detailed breakdowns of visual elements, copywriting, and overall scoring.

## Architecture

```
atomic/
├── api/
│   └── index.py              # FastAPI app with all endpoints
├── core/
│   ├── analyzer.py           # Core analysis logic & Groq integration
│   ├── prompts.py            # LLM system prompts
│   └── __init__.py
├── public/
│   ├── index.html            # Frontend SPA
│   └── ads/                  # Cached ad images (optional)
├── cache.json                # Pre-built analysis cache
├── requirements.txt          # Python dependencies
└── README.md                 # This file
```

### Tech Stack

- **Backend**: FastAPI 0.136.1
- **AI Provider**: Groq (Llama 4 Scout 17B model)
- **Image Processing**: Pillow
- **Server**: Uvicorn
- **Frontend**: HTML5 + Vanilla JavaScript
- **Environment**: Python-dotenv

### Data Flow

```
┌─────────────────────────────────────────────────┐
│         Frontend (public/index.html)            │
└──────────────┬──────────────────────────────────┘
               │ (upload images)
               ▼
┌─────────────────────────────────────────────────┐
│ FastAPI Routes (api/index.py)                   │
│ • POST /api/upload-and-analyze                  │
│ • GET  /api/analyze (demo)                      │
└──────────────┬──────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────┐
│ Analyzer Pipeline (core/analyzer.py)            │
│ • Image encoding (base64)                       │
│ • Groq API vision calls                         │
│ • JSON response parsing                         │
│ • Caching (optional)                            │
└──────────────┬──────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────┐
│         Groq Vision API                         │
│ (Meta Llama 4 Scout 17B - Vision)               │
└─────────────────────────────────────────────────┘
```

## Setup & Installation

### Prerequisites

- Python 3.8+
- pip
- Groq API key (get free credits at https://console.groq.com)

### 1. Clone & Navigate

```bash
cd Ads-Creative-Analyzer
```

### 2. Create Virtual Environment (Recommended)

```bash
python -m venv venv

# On Windows:
venv\Scripts\activate

# On macOS/Linux:
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Setup Environment Variables

Create a `.env` file in the root directory:

```env
GROQ_API_KEY=your_groq_api_key_here
```

**Get your Groq API key:**
1. Go to https://console.groq.com
2. Create an account
3. Navigate to API Keys
4. Copy your API key
5. Paste it in the `.env` file

## Running Locally

```bash
cd api
python -m uvicorn index:app --reload --host 0.0.0.0 --port 8000
```

Then open: http://localhost:8000

### Build Cache Locally (Optional)

To pre-build the `cache.json` with your own analysis:

```bash
python -c "from core.analyzer import run_pipeline; run_pipeline()"
```

> Note: This requires the `public/ads/` directory to contain PNG/JPG images

### POST `/api/upload-and-analyze`
**Requires:** 2-15 image files (PNG, JPG, WEBP, max 10MB each)

**Returns:** Same shape as GET `/api/analyze` with base64 encoded images

**Example:**
```bash
curl -X POST http://localhost:8000/api/upload-and-analyze \
  -F "files=@ad1.png" \
  -F "files=@ad2.jpg"
```

## Environment Variables

| Variable | Required | Example | Description |
|----------|----------|---------|-------------|
| `GROQ_API_KEY` | ✓ | `gsk_xxx...` | Groq API key for vision analysis |

### Key Functions

**`run_pipeline_from_uploads(image_files)`** - Main analysis function
- Takes list of (filename, bytes) tuples
- Returns structured breakdown + report

**`build_response_from_cache()`** - Cache helper
- Loads and formats pre-built analysis

**`_call_breakdown(client, b64)`** - Groq integration
- Single vision API call to Groq
