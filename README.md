# SmartHaul

SmartHaul is a starter implementation of a future-ready mobility, haulage, marketplace, and AI support platform.

## Features included
- Booking API for rides and haulage
- Vendor marketplace listing endpoint
- AI support endpoint
- Abuse report endpoint
- Admin metrics endpoint
- Test coverage for core workflows

## Run locally

### Backend
```bash
python -m pip install -r requirements.txt
uvicorn app:app --reload
```

Then open:
- http://127.0.0.1:8000/ for the dashboard view
- http://127.0.0.1:8000/docs for the API docs

## Free-tier deployment
Use the lightweight dependency file [requirements-free.txt](requirements-free.txt) if you want a simpler deployment target.
See [README_DEPLOY.md](README_DEPLOY.md) for hosting instructions.

### Tests
```bash
pytest -q
```
