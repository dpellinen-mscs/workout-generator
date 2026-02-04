# Deployment Guide

This app is ready to deploy with `gunicorn` and environment-based secrets.

## Required Env Vars

- `DATABASE_URL`: Postgres connection string
- `WG_SECRET_KEY`: long random string
- `WG_ADMIN_CODE`: admin registration code
- `WG_SECURE_COOKIES`: `1` in production (`0` locally)

## Local Production-Like Run

```bash
pip install -r requirements.txt
export DATABASE_URL="postgresql://USER:PASSWORD@HOST:5432/DBNAME"
export WG_SECRET_KEY="replace-me"
export WG_ADMIN_CODE="replace-me"
export WG_SECURE_COOKIES=0
gunicorn app:app --workers 2 --threads 4 --timeout 120 --bind 0.0.0.0:8000
```

## Render (Recommended)

Use `render.yaml` in this repo.

Manual settings if needed:

- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app --workers 2 --threads 4 --timeout 120 --bind 0.0.0.0:$PORT`
- Env vars:
  - `DATABASE_URL` (from Render Postgres)
  - `WG_SECRET_KEY` (generated)
  - `WG_ADMIN_CODE` (set manually)
  - `WG_SECURE_COOKIES=1`

## Railway

- Start command: `gunicorn app:app --workers 2 --threads 4 --timeout 120 --bind 0.0.0.0:$PORT`
- Add env vars:
  - `WG_SECRET_KEY`
  - `WG_ADMIN_CODE`
  - `WG_SECURE_COOKIES=1`

## Fly.io

After `fly launch`, set app command to:

```bash
gunicorn app:app --workers 2 --threads 4 --timeout 120 --bind 0.0.0.0:$PORT
```

Then set secrets:

```bash
fly secrets set WG_SECRET_KEY="replace-me" WG_ADMIN_CODE="replace-me" WG_SECURE_COOKIES=1
```
