# SmartHaul Free Deployment Guide

This project is designed to run as a free-tier starter using open-source tools and low-cost or free hosting options.

## Recommended free hosting options
- Render
- Railway
- Fly.io
- GitHub Pages for static assets only
- Azure App Service free tier where available

## What is included for free deployment
- Python/FastAPI backend
- Jinja templates for frontend views
- SQLite database for lightweight persistence
- No paid API dependency required for the starter experience

## Deploy steps
1. Push the project to GitHub.
2. Create a new web service on Render.
3. Render will use the included [render.yaml](render.yaml) configuration automatically.
4. Deploy.

### Manual Render settings
- Build command: `pip install -r requirements-free.txt`
- Start command: `uvicorn app:app --host 0.0.0.0 --port $PORT`

## Notes
- SQLite is suitable for prototype and local testing.
- For production scale, move to PostgreSQL later.
- For maps and routing, use open-source providers such as OpenStreetMap-based services.
