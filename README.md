# Booth Scanner Bot

Telegram bot that analyzes conference booth photos, identifies companies, and ranks them against your Ideal Customer Profile (ICP).

## How it works

1. Set your ICP via `/seticp` in the Telegram chat
2. Take a photo of conference booths and send it to the bot
3. The bot identifies company logos using Claude Vision
4. Researches each company via Tavily web search
5. Scores and ranks companies against your ICP
6. Returns a prioritized list with match reasons

## Prerequisites

You need three API keys:

| Service | Get it from | Free tier |
|---|---|---|
| Telegram Bot Token | [@BotFather](https://t.me/BotFather) | Free |
| Anthropic API Key | [console.anthropic.com](https://console.anthropic.com) | Pay-as-you-go (~$0.02/photo) |
| Tavily API Key | [app.tavily.com](https://app.tavily.com) | 1,000 searches/month free |

## Deploy to Railway (recommended)

1. Fork this repo or push to your own GitHub
2. Go to [railway.app](https://railway.app), create a new project from your repo
3. Add environment variables in the Railway dashboard:
   ```
   TELEGRAM_BOT_TOKEN=your-token
   ANTHROPIC_API_KEY=your-key
   TAVILY_API_KEY=your-key
   ```
4. Railway will auto-detect the Dockerfile and deploy

The bot runs in polling mode - no webhook or domain setup needed.

## Deploy with Docker (any VPS)

```bash
docker build -t booth-scanner-bot .
docker run -d --name booth-bot \
  -e TELEGRAM_BOT_TOKEN=your-token \
  -e ANTHROPIC_API_KEY=your-key \
  -e TAVILY_API_KEY=your-key \
  -v booth-data:/app/data \
  booth-scanner-bot
```

## Run locally (development)

```bash
cp .env.example .env
# Fill in your API keys in .env
pip install -e .
python -m bot.main
```

## Bot commands

- `/start` - Welcome message
- `/seticp <description>` - Set your ICP (e.g., `/seticp B2B SaaS, 50-500 employees, Series A+, US-based`)
- `/showicp` - View your current ICP
- `/help` - List commands
- **Send a photo** - Triggers booth analysis

## Cost per photo

~$0.06-0.14 depending on how many companies are detected (Claude Vision + Tavily searches + Claude matching).
