#!/usr/bin/env python3
"""
Quick troubleshooting guide for SmartHaul Render deployment.
"""

import os

print("""
╔════════════════════════════════════════════════════════════════════════════╗
║                    SMARTHAUL RENDER DEPLOYMENT CHECKLIST                   ║
╚════════════════════════════════════════════════════════════════════════════╝

⚠️  CURRENT ISSUE: Health endpoint hangs with read timeout
    → Server accepts connections but doesn't respond

🔍 MOST LIKELY CAUSES (in order):
  1. SECRET_KEY not set on Render dashboard (Django will crash)
  2. New build (f8c190d) not yet deployed by Render  
  3. PostgreSQL connection hanging despite DATABASE_URL set

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📋 IMMEDIATE ACTION STEPS:

1️⃣  VERIFY SECRET_KEY on Render Dashboard
   ────────────────────────────────────────
   Go to: https://dashboard.render.com/web/srv-d997ed1o3t8c73f0eph0/env
   
   ❓ Do you see "SECRET_KEY" in the environment variables list?
   
   If NO:
   • Click "Add Environment Variable"
   • Key: SECRET_KEY
   • Value: Copy from your local .env file or generate new
   • Save and trigger Manual Deploy
   
   If YES:
   • Proceed to step 2

2️⃣  CHECK BUILD STATUS
   ───────────────────
   Go to: https://dashboard.render.com/web/srv-d997ed1o3t8c73f0eph0/events
   
   Look at recent deployments:
   • Find the most recent one (timestamp ~10:37-10:40 UTC)
   • Check if it says "Deploy succeeded" or is still building
   
   If STILL BUILDING (> 5 minutes):
   • Click "Manual Deploy" to force restart
   
   If DEPLOY FAILED:
   • Click on the deploy to see detailed error logs
   • Look for keywords: "psycopg2", "migration", "ImportError", "SECRET_KEY"
   • Share the error with troubleshooting

3️⃣  MANUAL TEST (if still failing)
   ────────────────────────────────
   Run locally to verify app works:
   
   $ python django_smarthaul/manage.py runserver
   
   In another terminal:
   $ python verify_deploy.py --base-url http://localhost:8000
   
   If local test FAILS:
   • Issue is in Django code, not Render configuration
   • Check: python django_smarthaul/manage.py check

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔧 REQUIRED ENV VARIABLES (must all be set on Render dashboard):

✓ SECRET_KEY          → Set to your Django secret key
✓ DEBUG               → Set to "false" for production
✓ ALLOWED_HOSTS       → Already configured in render.yaml
✓ DATABASE_URL        → Already in render.yaml (hardcoded)
✓ ENVIRONMENT         → Already in render.yaml ("production")

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

💡 QUICK FIX IF ABOVE DOESN'T WORK:
   
   Option 1: Simplify the build command temporarily
   ──────────────────────────────────────────────────
   Replace in render.yaml buildCommand with:
   
   pip install -r django_smarthaul/requirements.txt && python django_smarthaul/manage.py collectstatic --noinput
   
   This skips migrations entirely, letting app start with SQLite fallback.
   Then use Render shell to run migrations separately.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 LATEST GIT COMMITS:
""")

print("\n✓ Latest 5 commits:")
os.system('git log --oneline -5')

print("\n\n✓ Current status:")
os.system('git status --short')

print("\n" + "="*76)
print("Next: Follow steps above and report findings")
