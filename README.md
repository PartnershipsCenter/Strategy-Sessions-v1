# Strategy-Sessions-v1

Fireflies.ai integration that automatically pulls raw meeting transcripts to your local machine after each call.

## Setup

1. Install dependencies:
   ```
   npm install
   ```

2. Copy `.env.example` to `.env` and fill in your values:
   ```
   cp .env.example .env
   ```

   - **FIREFLIES_API_KEY** — Get from [Fireflies Integrations](https://app.fireflies.ai/integrations) > Fireflies API
   - **WEBHOOK_SECRET** — Set in [Fireflies Developer Settings](https://app.fireflies.ai/settings) (16-32 chars)
   - **PORT** — Server port (default: 3000)
   - **TRANSCRIPT_DIR** — Where to save transcripts (default: ~/Documents/transcripts)

3. Configure the webhook in Fireflies:
   - Go to **app.fireflies.ai/settings** > Developer Settings
   - Set webhook URL to your server's public URL + `/webhook` (e.g., `https://your-domain.com/webhook`)
   - Set a webhook secret and copy it to your `.env`

## Usage

### Webhook server (automatic)

Start the server to automatically receive and save transcripts after each call:

```
npm run dev      # development (ts-node)
npm run build    # compile TypeScript
npm start        # production (compiled JS)
```

The server exposes:
- `POST /webhook` — receives Fireflies notifications
- `GET /health` — health check

### Manual pull (CLI)

Pull transcripts on demand:

```
npm run pull -- recent          # pull 10 most recent transcripts
npm run pull -- recent 25       # pull 25 most recent
npm run pull -- get <id>        # pull a specific transcript by ID
```

## Output

Each transcript is saved in two formats:
- **`.txt`** — human-readable with speaker labels and timestamps
- **`.json`** — full raw API response

Files are named: `YYYY-MM-DD_Meeting_Title_transcriptId.{txt,json}`

## Exposing locally for webhooks

For local development, use a tunnel like [ngrok](https://ngrok.com):

```
ngrok http 3000
```

Then set the ngrok URL as your webhook URL in Fireflies settings.
