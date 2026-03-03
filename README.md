# Conference Exhibitor Scanner

Scrape conference exhibitor lists (MWC, Web Summit, GDC, LEAP, Token2049, SaaStr, etc.), enrich them with web research, and score against your Ideal Customer Profile (ICP).

**Two interfaces:**
- **Web App** — clean UI with real-time progress, sortable results table, CSV export
- **Telegram Bot** — `/scan <URL>` command + booth photo analysis

## How It Works

```
1. Scrape exhibitor list    Playwright opens the page, detects pagination
                             (API sniffing > server-side pages > JS click-through)
                             Collects company names + detail page URLs

2. Scrape detail pages       Visits each exhibitor's profile page
                             Extracts: website, LinkedIn, contact, description

3. Enrich via web search     Tavily searches for company info + leadership
                             Fills gaps for exhibitors missing descriptions

4. Score against ICP         Claude scores each company 1-10 in batches
                             Includes CIS-origin leadership detection
                             Returns top 50 with reasoning

5. Store in knowledge base   SQLite DB persists everything
                             Re-score with different ICPs without re-scraping
```

## Quick Start

```bash
# Clone and install
git clone <repo-url> && cd conference-scanner
pip install -e .
playwright install chromium

# Configure
cp .env.example .env
# Edit .env with your API keys

# Run web app
python -m api.main
# Open http://localhost:8080

# Or run Telegram bot
python -m bot.main
```

## API Keys Required

| Service | Purpose | Get it at |
|---------|---------|-----------|
| **Anthropic** | LLM extraction + ICP scoring | https://console.anthropic.com |
| **Tavily** | Web search enrichment | https://tavily.com |
| **Telegram** | Bot (optional) | https://t.me/BotFather |

## Cost per Conference Scan

| Step | Model/Service | Est. Cost |
|------|---------------|-----------|
| HTML extraction | Claude Haiku | ~$0.01 |
| Detail page extraction | Claude Haiku | ~$0.30 |
| Web search enrichment | Tavily | ~$0.50 |
| ICP scoring | Claude Sonnet | ~$0.40 |
| **Total** | | **~$1.20** |

## Docker Deployment

```bash
docker build -t conference-scanner .
docker run -p 8080:8080 \
  -e ANTHROPIC_API_KEY=sk-... \
  -e TAVILY_API_KEY=tvly-... \
  -v $(pwd)/data:/app/data \
  conference-scanner
```

For Telegram bot only:
```bash
docker run \
  -e ANTHROPIC_API_KEY=sk-... \
  -e TAVILY_API_KEY=tvly-... \
  -e TELEGRAM_BOT_TOKEN=... \
  -v $(pwd)/data:/app/data \
  conference-scanner python -m bot.main
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | Yes | — | Anthropic API key |
| `TAVILY_API_KEY` | Yes | — | Tavily search API key |
| `TELEGRAM_BOT_TOKEN` | For bot | — | Telegram bot token |
| `CLAUDE_MODEL_EXTRACT` | No | `claude-haiku-4-5` | Model for extraction |
| `CLAUDE_MODEL_SCORE` | No | `claude-sonnet-4-6` | Model for scoring |
| `DB_PATH` | No | `data/conference_scanner.db` | SQLite database path |
| `PORT` | No | `8080` | Web server port |
| `WEBHOOK_URL` | No | — | Telegram webhook URL |
| `SCRAPE_DELAY` | No | `1.0` | Delay between detail page fetches (seconds) |
| `MAX_DETAIL_PAGES` | No | `1000` | Max detail pages to scrape |

## Telegram Bot Commands

| Command | Description |
|---------|-------------|
| `/seticp <text>` | Set your Ideal Customer Profile |
| `/showicp` | Show your current ICP |
| `/scan <URL>` | Scan a conference exhibitor list |
| `/help` | Show help |
| *Send a photo* | Analyze booth logos from a photo |

## Project Structure

```
conference-scanner/
  core/           Shared backend logic
    config.py       Configuration
    db.py           SQLite knowledge base
    scraper.py      Playwright two-pass scraper
    extractor.py    LLM-based HTML extraction
    enricher.py     Tavily web search enrichment
    scorer.py       ICP scoring pipeline
    pipeline.py     Full orchestrator
  api/            FastAPI web backend
    main.py         App entry point
    routes.py       API endpoints + SSE
  web/            Frontend (single-page app)
    index.html
    style.css
    app.js
  bot/            Telegram bot
    main.py         Bot entry point
    handlers.py     Command handlers (/scan, /seticp, photo)
    vision.py       Claude Vision (booth photos)
    search.py       Tavily research (photo pipeline)
    matcher.py      ICP scoring (photo pipeline)
    formatter.py    Telegram message formatting
    icp_store.py    ICP storage wrapper
  data/           SQLite database (gitignored)
```
