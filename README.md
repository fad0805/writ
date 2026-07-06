# WRIT

ActivityPub‑federated serial novel platform.

## Tech Stack

| Layer | Stack |
|---|---|
| Backend | Python 3.12 / FastAPI / SQLAlchemy / SQLite (dev) / PostgreSQL (prod) |
| Frontend | Next.js 16 / React 19 / TypeScript / Tailwind CSS v4 |
| Federation | ActivityPub with HTTP Signatures, HTML content, mention tags |
| Storage | Local disk (dev) or S3‑compatible object storage (via `utils/storage.py`) |

## Quick Start

```bash
./dev.sh
```

Opens backend on `localhost:8000` and frontend on `localhost:3000`.  
Edit `.env.development` for local overrides.

## Environment

| Variable | Default | Description |
|---|---|---|
| `DOMAIN` | `localhost:8080` | Public domain |
| `SCHEME` | `http` | `http` or `https` |
| `DATABASE_URL` | `sqlite:///./sns_blog.db` | SQLAlchemy DB URL |
| `SECRET_KEY` | `change-me-…` | Session signing key |
| `STORAGE_BACKEND` | `local` | `local` or `s3` |
| `S3_ENDPOINT` | — | S3 endpoint URL |
| `S3_BUCKET` | — | S3 bucket name |
| `S3_PUBLIC_URL` | — | Public base URL for S3 objects |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma‑separated CORS origins |

Full list in `config.py`.

## Deployment

1. Copy `.env.production` → fill in real values
2. `APP_ENV=production ./dev.sh`

## Project Layout

```
├── main.py              # FastAPI app, routes, middleware
├── models.py            # SQLAlchemy models
├── activitypub.py       # ActivityPub inbox/outbox, federation helpers
├── config.py            # Environment config
├── crypto_utils.py      # Key encryption (Fernet)
├── utils/
│   └── storage.py       # Storage abstraction (LocalStorage / S3Storage)
├── routes/
│   └── api.py           # REST API endpoints
├── web/                 # Next.js frontend
└── static/              # Static assets
```
