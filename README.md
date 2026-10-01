# Reels Downloader

## Highlights

- TikTok videos and Instagram Reels, posts, photos, carousels, and accessible Stories
- Single-link and batch downloads with duplicate detection and configurable limits
- Arabic and English interface with onboarding, help, settings, and privacy flows
- Async queue with per-user locks, concurrency limits, cooldowns, and rate limiting
- Resilient extraction with retries, engine fallback, file validation, and Telegram fallback
- Automatic temporary-file cleanup, admin statistics, health endpoints, Docker, and Railway support
- SQLite persistence through a repository layer that can later be replaced with PostgreSQL

The bot handles public media only. It does not bypass private accounts or access controls, and it never asks users for passwords.

## Requirements

- Python 3.12+
- FFmpeg
- Telegram bot token from [@BotFather](https://t.me/BotFather)

## Quick start

```bash
git clone https://github.com/abdelhamednada631-del/reels-downloader.git
cd reels-downloader
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env           # Set BOT_TOKEN and, optionally, ADMIN_IDS
python -m app.main
```

The bot uses long polling; run only one active instance per Telegram bot token.

## Configuration

Copy `.env.example` to `.env` and never commit real secrets.

| Variable | Purpose | Default |
| --- | --- | --- |
| `BOT_TOKEN` | Telegram bot token | required |
| `ADMIN_IDS` | Comma-separated admin Telegram IDs | empty |
| `DATABASE_URL` | SQLite URL | `sqlite:///bot.db` |
| `MAX_FILE_SIZE_MB` | Maximum delivered file size | `50` |
| `DOWNLOAD_TIMEOUT` | Download timeout in seconds | `120` |
| `MAX_CONCURRENT_DOWNLOADS` | Global download limit | `3` |
| `MAX_BATCH_SIZE` | Links per batch | `5` |
| `MAX_MEDIA_PER_POST` | Items per carousel | `10` |
| `ENGINE_ATTEMPTS` | Attempts before engine fallback | `2` |
| `RETRY_BASE_DELAY` | Exponential retry base delay | `2` |
| `RATE_LIMIT_SECONDS` | Minimum interval between requests | `10` |
| `MAX_REQUESTS_PER_MINUTE` | Per-user rolling limit | `6` |
| `COOLDOWN_SECONDS` | Additional user cooldown | `3` |
| `TEMP_RETENTION_MINUTES` | Temporary-file retention | `60` |
| `DEFAULT_LANGUAGE` | `ar` or `en` | `ar` |
| `AUTO_DELETE` | Remove temporary files | `true` |
| `DROP_PENDING_UPDATES` | Drop queued updates on boot | `false` |
| `PORT` | Health-server port; `0` disables it | `0` |
| `INSTAGRAM_COOKIES_BASE64` | Optional runtime Instagram cookies | empty |

## Docker and Railway

```bash
docker build -t reels-downloader .
docker run --env-file .env reels-downloader
```

For Railway, create a service from this repository, use the included `Dockerfile` and `railway.toml`, and add `BOT_TOKEN` and `ADMIN_IDS` as service variables. Set `PORT` to enable `/healthz` or `/readyz` checks.

SQLite is suitable for a simple single-instance deployment but is not durable across every container replacement. Use a PostgreSQL-backed repository for durable production data, and keep one polling instance per bot token.

## Instagram session cookies

Some Instagram media requires a valid session. If you are authorized to access it:

1. Export your own cookies as Netscape `cookies.txt`.
2. Encode them locally: `base64 -w 0 cookies.txt`.
3. Store the result in the `INSTAGRAM_COOKIES_BASE64` deployment secret.
4. Never commit the cookie file or encoded value; rotate the session if exposed.

Cookies are materialized only at runtime and removed during shutdown.

## Commands

`/start` · `/download` · `/batch` · `/stats` · `/history` · `/settings` · `/privacy` · `/help` · `/admin`

## Tests

```bash
python -m pytest -q
```

The suite covers URL validation, cookies, localization, rate limiting, download management, delivery, repository operations, batch locking, and cleanup flows.

## Project structure

```text
app/bot/       Handlers, keyboards, and localization
app/database/  SQLite connection, models, and repository
app/locales/   Arabic and English translations
app/services/  Download, validation, health, cleanup, and limits
tests/         Automated test suite
```

## Security and privacy

- Keep `BOT_TOKEN`, admin IDs, and Instagram cookies out of Git.
- The URL validator rejects local and private network targets.
- Temporary media is removed according to the configured retention period.
- Download only material you have permission to use.
- Third-party platforms and Telegram upload limits can change.

## License

No license file is currently included. Add one before redistributing the project or accepting external contributions.
