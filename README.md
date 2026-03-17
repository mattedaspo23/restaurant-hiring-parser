# Restaurant Hiring Profile Parser

Un sistema ATS (Applicant Tracking System) specializzato per il settore della ristorazione italiana. Raccoglie automaticamente profili candidati da Indeed.it, EasyJob.it e upload diretti di CV (PDF/DOCX), li analizza con NLP (spaCy + OpenAI), applica filtri configurabili dal manager e presenta una dashboard interattiva Streamlit con shortlist, heatmap e analytics.

## Prerequisites

- **Python 3.11+**
- **Docker & Docker Compose**
- **Tesseract OCR** — per il fallback OCR su PDF scansionati (`apt install tesseract-ocr tesseract-ocr-ita`)
- **Playwright browsers** — installati automaticamente nel Docker, oppure `playwright install chromium` per sviluppo locale
- **Supabase account** — per il database (o un'istanza self-hosted)
- **OpenAI API key** — per il fallback NLP quando spaCy non riesce a estrarre tutti i campi

## Local Setup

```bash
# 1. Clone the repository
git clone <repo-url>
cd restaurant-hiring-parser

# 2. Copy environment file and fill in your keys
cp .env.example .env
# Edit .env with your Supabase URL, Supabase key, OpenAI API key

# 3. Build and run with Docker Compose
docker-compose up --build

# Backend available at: http://localhost:8010
# Frontend available at: http://localhost:8511
```

### Local development without Docker

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements-backend.txt
pip install -r requirements-frontend.txt

# Download spaCy Italian model
python -m spacy download it_core_news_sm

# Install Playwright browsers
playwright install chromium

# Run backend
uvicorn backend.main:app --host 0.0.0.0 --port 8010 --reload

# Run frontend (in another terminal)
BACKEND_URL=http://localhost:8010 streamlit run frontend/app.py --server.port 8511
```

## Hetzner Deploy

```bash
# SSH to your Hetzner server
ssh root@your.server.ip

# Clone the repo
git clone <repo-url>
cd restaurant-hiring-parser

# Copy and configure environment
cp .env.example .env
nano .env  # fill in production values

# Run in production mode
docker-compose -f docker-compose.yml up -d

# Check logs
docker-compose logs -f
```

## Supabase Schema

Run the following SQL in your Supabase SQL editor to create the required tables:

```sql
-- Candidates table
CREATE TABLE candidates (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    years_of_experience FLOAT DEFAULT 0,
    skills JSONB DEFAULT '[]'::jsonb,
    certifications JSONB DEFAULT '[]'::jsonb,
    has_haccp BOOLEAN DEFAULT FALSE,
    availability TEXT DEFAULT '',
    languages JSONB DEFAULT '[]'::jsonb,
    source TEXT NOT NULL,
    source_url TEXT,
    source_hash TEXT UNIQUE,
    raw_text TEXT,
    email TEXT,
    phone TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_candidates_source ON candidates(source);
CREATE INDEX idx_candidates_role ON candidates(role);
CREATE INDEX idx_candidates_source_hash ON candidates(source_hash);

-- Filter configurations table
CREATE TABLE filter_configs (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    min_years_exp FLOAT DEFAULT 0,
    required_certs JSONB DEFAULT '[]'::jsonb,
    availability TEXT DEFAULT '',
    languages JSONB DEFAULT '[]'::jsonb,
    bonus_filters JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Scoring history table
CREATE TABLE scoring_history (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    candidate_id UUID REFERENCES candidates(id) ON DELETE CASCADE,
    config_id UUID REFERENCES filter_configs(id) ON DELETE CASCADE,
    score FLOAT NOT NULL,
    strengths JSONB DEFAULT '[]'::jsonb,
    gaps JSONB DEFAULT '[]'::jsonb,
    scored_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_scoring_config ON scoring_history(config_id);
CREATE INDEX idx_scoring_candidate ON scoring_history(candidate_id);
```

## How to Add a New Scraper Source

1. Create a new file in `backend/ingestion/`, e.g. `backend/ingestion/my_source.py`
2. Implement a function `fetch_my_source_listings(role: str) -> List[dict]` that returns a list of dicts with at least `raw_text`, `source`, and optionally `url`, `title`, `company`, `location`
3. Always include Playwright as the fallback scraper:
   ```python
   from playwright.sync_api import sync_playwright

   def _playwright_fallback(role: str) -> List[dict]:
       with sync_playwright() as p:
           browser = p.chromium.launch(headless=True)
           # ... scraping logic ...
           browser.close()
       return listings
   ```
4. Add a new endpoint in `backend/main.py`:
   ```python
   @app.post("/api/ingest/my_source")
   async def ingest_my_source(request: IngestRequest):
       listings = fetch_my_source_listings(role=request.role)
       # ... process with parse_candidate and upsert ...
   ```
5. Update the frontend to include the new source in the import section

## How Filter JSON Config Works

Filter configurations are stored as JSON and define both **hard filters** (exclude non-matching candidates) and **soft scoring** (rank remaining candidates 0-100).

### Example Filter Config

```json
{
    "name": "Cuoco Senior Milano",
    "role": "cuoco",
    "min_years_exp": 3.0,
    "required_certs": ["HACCP", "SAB"],
    "availability": "full-time",
    "languages": ["Italiano", "Inglese"],
    "bonus_filters": {
        "skills": ["cucina italiana", "pasticceria", "food cost"],
        "weights": [1.5, 1.0, 1.2]
    }
}
```

### Hard Filters (Step 1 — Exclude)
- **role**: Exact match required
- **min_years_exp**: Candidate must have >= this many years
- **required_certs**: Candidate must have ALL listed certifications
- **availability**: Must match (with alias normalization)
- **languages**: At least ONE must match

### Soft Scoring (Step 2 — Rank 0-100)
- Base score: 50
- +10 per year of experience above minimum (capped at +30)
- +15 if HACCP certified
- +5 per extra matching language
- +5 × weight per matching bonus skill
- Floor: 0, Cap: 100

## API Endpoints Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Health check |
| POST | `/api/upload/cv` | Upload CV (PDF/DOCX) |
| POST | `/api/ingest/indeed` | Trigger Indeed.it scraping |
| POST | `/api/ingest/easyjob` | Trigger EasyJob.it scraping |
| GET | `/api/candidates` | List all candidates (optional ?role=&source=) |
| GET | `/api/candidates/{id}` | Get single candidate |
| GET | `/api/filters` | List all filter configs |
| POST | `/api/filters` | Save new filter config |
| GET | `/api/filters/{id}` | Get single filter config |
| POST | `/api/score` | Run filter engine (body: {"config_id": "..."}) |
| GET | `/api/scoring-history` | Get scoring history (optional ?config_id=) |
| GET | `/api/analytics/sources` | Source breakdown counts |
| GET | `/api/analytics/trends` | Candidates per day trend |
