# WRIT

ActivityPub‑federated serial novel platform.

## Tech Stack

| Layer | Stack |
|---|---|
| Backend | Python 3.12 / FastAPI / SQLAlchemy / SQLite (dev) / PostgreSQL (prod) |
| Frontend | Next.js 16 / React 19 / TypeScript |
| Federation | ActivityPub with HTTP Signatures, HTML content, mention tags |
| Storage | Local disk (dev) or S3‑compatible object storage (via `utils/storage.py`) |

## Quick Start

```bash
./dev.sh
```

Opens backend on `localhost:8000` and frontend on `localhost:3000`.  
Edit `.env.development` for local overrides.

## Seed Accounts

The first run creates sample data:

| Username | Password | Role |
|---|---|---|
| owner | `owner1234` | owner (모든 권한) |
| admin | `admin1234` | admin |
| moderator | `mod1234` | moderator (조율자) |
| author1 | `test1234` | user |
| reader1 | `test1234` | user |

- **owner**: full access to admin & moderation, gold books icon
- **admin**: full access to admin & moderation
- **moderator**: access to moderation pages (users, reports)

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
| `SMTP_SERVER` | — | SMTP server for moderation emails |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USER` | — | SMTP user |
| `SMTP_PASSWORD` | — | SMTP password |
| `SMTP_FROM` | — | SMTP sender address |

Full list in `app/config.py`.

## Project Layout

```
├── app/
│   ├── main.py              # FastAPI app, lifespan, CORS, SSE
│   ├── models.py            # SQLAlchemy models
│   ├── activitypub.py       # ActivityPub inbox/outbox, federation
│   ├── config.py            # Environment config
│   ├── crypto_utils.py      # Key encryption (Fernet)
│   ├── eventbus.py          # Server-Sent Events bus
│   ├── routes/
│   │   ├── api.py           # REST API endpoints
│   │   ├── auth.py          # Auth helpers (login, register, sessions)
│   │   ├── sns.py           # ActivityPub S2S routes
│   │   └── admin.py         # Admin-specific routes
│   └── utils/
│       └── storage.py       # Storage abstraction (Local / S3)
├── web/                     # Next.js frontend
├── migrate.py               # DB migration script
├── dev.sh                   # Dev server launcher
└── static/                  # Static assets
```

## Deployment

Copy `.env.production` → fill in real values, then run the backend with uvicorn directly or via your process manager.

```bash
uvicorn app.main:app
```

## Admin Pages

| Path | Description |
|---|---|
| `/admin` | Dashboard (stats) |
| `/admin/users` | User management (search, suspend, filter) |
| `/admin/users/{id}` | User detail (moderation, email, role) |
| `/admin/reports` | Report queue |
| `/admin/emojis` | Custom emoji management |
| `/admin/settings` | Server settings (name, icons, admin list) |

## DB Reset

To start with a fresh database, delete `sns_blog.db` and restart the server.
`Base.metadata.create_all(engine)` recreates all tables on startup.
