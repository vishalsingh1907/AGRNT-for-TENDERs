# 🏗️ AI Tender Monitoring Agent

An AI-powered, production-ready tender monitoring system for **Industrial Automation & Electrical Engineering** companies. Automatically scrapes government tender portals, analyzes relevance using Google Gemini AI, and sends smart notifications via Telegram.

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🌐 **Multi-Source Scraping** | CPPP, GeM, NTPC, BHEL, BEL, ONGC, BidAssist |
| 🤖 **AI Analysis** | Gemini-powered relevance scoring (0-100) with structured output |
| 📊 **Admin Dashboard** | FastAPI + Jinja2 web UI with search, filters, and stats |
| 📱 **Telegram Bot** | Notifications + commands (`/latest`, `/today`, `/search`, `/stats`) |
| 🗄️ **SQLite** | Persistent storage with async operations and deduplication |
| 📄 **PDF Processing** | Download and extract text from tender documents |
| ⏰ **Scheduled Runs** | APScheduler with configurable intervals (default: 6 hours) |
| 🐳 **Docker Ready** | Full Docker Compose setup with health checks |
| 🔌 **Pluggable Sources** | Add new portals via YAML config — no code changes |

## 📁 Project Structure

```
tender-agent/
├── config/
│   ├── settings.py          # Environment config (Pydantic)
│   └── sources.yaml         # Tender sources config (pluggable)
├── models/
│   └── tender.py            # SQLAlchemy ORM model
├── database/
│   ├── connection.py        # Async engine & session factory
│   └── operations.py        # CRUD operations & statistics
├── scraper/
│   ├── base.py              # Abstract base scraper (Playwright)
│   ├── cppp_scraper.py      # CPPP portal scraper
│   ├── gem_scraper.py       # GeM portal scraper
│   ├── psu_scraper.py       # PSU scraper (NTPC, BHEL, BEL, ONGC)
│   ├── bidassist_scraper.py # BidAssist scraper
│   └── pdf_downloader.py    # PDF download & text extraction
├── ai/
│   ├── prompts.py           # Prompt templates & Pydantic schemas
│   └── analyzer.py          # Gemini/OpenAI tender analyzer
├── notifications/
│   └── telegram.py          # Telegram notifications & bot commands
├── scheduler/
│   └── jobs.py              # APScheduler job orchestration
├── dashboard/
│   ├── app.py               # FastAPI admin dashboard
│   └── templates/           # Jinja2 HTML templates
├── main.py                  # Application entry point
├── requirements.txt         # Python dependencies
├── Dockerfile               # Container image
├── docker-compose.yml       # Full stack deployment
├── .env.example             # Environment variable template
└── README.md                # This file
```

## 🏗️ Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Scrapers   │────▶│    SQLite    │────▶│  AI Analyzer │
│  (Playwright)│     │ (aiosqlite)  │     │   (Gemini)   │
└──────────────┘     └──────────────┘     └──────────────┘
       │                    │                     │
       │              ┌─────┴─────┐              │
       │              │ Dashboard │              │
       │              │ (FastAPI) │              │
       │              └───────────┘              │
       │                                         │
       ▼                                         ▼
┌──────────────┐                         ┌──────────────┐
│ PDF Download │                         │   Telegram   │
│  & Extract   │                         │    Notify    │
└──────────────┘                         └──────────────┘
```

**Pipeline Flow:** Scrape → Deduplicate → Store → Download PDFs → AI Analysis → Score → Notify (if ≥75)

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.12+**
- **Docker & Docker Compose** (for deployment)
- **Google Gemini API key** — [Get one here](https://aistudio.google.com/apikey)
- **Telegram Bot** — [Create via @BotFather](https://t.me/BotFather)

### Option A: Docker Compose (Recommended)

```bash
# 1. Clone the project
cd tender-agent

# 2. Create your .env file
cp .env.example .env
# Edit .env with your API keys and Telegram credentials

# 3. Start everything
docker-compose up -d

# 4. Check logs
docker-compose logs -f agent

# 5. Open the dashboard
# http://localhost:8000
```

### Option B: Local Development

```bash
# 1. Create and activate virtual environment
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Install Playwright browser
playwright install chromium



# 5. Create .env file
cp .env.example .env
# Edit .env — set your GEMINI_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

# 6. Run the agent
python main.py

# Or run with an immediate scraping cycle:
python main.py --run-now

# 7. Open the dashboard
# http://localhost:8000
```

---

## ⚙️ Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GEMINI_API_KEY` | ✅ | — | Google Gemini API key |
| `TELEGRAM_BOT_TOKEN` | ✅ | — | Telegram Bot API token |
| `TELEGRAM_CHAT_ID` | ✅ | — | Target Telegram chat/group ID |
| `DATABASE_URL` | No | `sqlite+aiosqlite:///tender_agent.db` | Async SQLite URL |
| `AI_PROVIDER` | No | `gemini` | `gemini` or `openai` |
| `AI_MODEL` | No | `gemini-2.5-flash` | AI model name |
| `SCRAPE_INTERVAL_HOURS` | No | `6` | Hours between scraping cycles |
| `RELEVANCE_THRESHOLD` | No | `75` | Min score for Telegram alerts |
| `LOG_LEVEL` | No | `INFO` | Logging level |
| `DASHBOARD_PORT` | No | `8000` | Dashboard web server port |

### Adding New Tender Sources

Edit `config/sources.yaml` — **no code changes required:**

```yaml
sources:
  - name: "MyNewPortal"
    scraper_class: "scraper.cppp_scraper.CPPPScraper"  # or create a new scraper
    base_url: "https://example.com/tenders"
    enabled: true
    search_keywords:
      - "automation"
      - "electrical"
    max_pages: 5
    extra:
      organization_filter: "MyOrg"
```

---

## 📱 Telegram Bot Commands

| Command | Description |
|---------|-------------|
| `/latest` | Show the 5 most recent tenders |
| `/today` | Show tenders added today |
| `/search <keyword>` | Search tenders by keyword (e.g., `/search SCADA`) |
| `/stats` | Show database statistics and score distribution |
| `/help` | Show available commands |

---

## 📊 Dashboard

Access at `http://localhost:8000`

**Pages:**
- **Dashboard** (`/`) — Stats overview, score distribution, recent tenders
- **Tenders** (`/tenders`) — Full listing with search and filters
- **Tender Detail** (`/tender/{id}`) — AI analysis, requirements, eligibility, scope
- **System** (`/logs`) — Uptime, config, last cycle report, API endpoints
- **Health** (`/health`) — JSON health check

**API Endpoints:**
- `GET /health` — System health
- `GET /api/stats` — Aggregate statistics
- `GET /api/tenders?search=keyword&limit=20` — List tenders
- `GET /api/tender/{id}` — Single tender detail

---

## 🤖 AI Analysis Output

Each tender is analyzed with the following structured JSON output:

```json
{
  "relevance_score": 85,
  "is_relevant": true,
  "key_requirements": ["PLC Siemens S7-1500", "SCADA system", "MCC Panel"],
  "emd_amount": "INR 5,00,000",
  "eligibility_criteria": ["Min 3 years experience", "ISO 9001 certified"],
  "scope_of_work": "Design, supply, and commissioning of PLC-SCADA system...",
  "summary": "NTPC seeks automation contractor for...",
  "matched_keywords": ["PLC", "SCADA", "MCC Panel", "Siemens"],
  "recommendation": "Highly Recommended"
}
```

---

## 🔧 Troubleshooting

| Issue | Solution |
|-------|----------|
| Playwright browser not found | Run `playwright install chromium` |

| Telegram messages not sending | Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` |
| AI analysis returning fallback | Check `GEMINI_API_KEY` is valid |
| Docker build fails | Ensure Docker has at least 4GB RAM allocated |
| Scraper returning 0 results | Portal may have anti-bot protection; check logs |

---

## 📄 License

MIT License — use freely for commercial and personal projects.
