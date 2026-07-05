SmartHaul Django Migration Commit Manifest (Strict Explicit)

Purpose
- Reconstruct the original 3-commit split for the FastAPI/Uvicorn to Django/DRF/Gunicorn migration.
- Use only explicit single-file staging commands.

Important
- Keep django_smarthaul/.vscode/tasks.json out of commits.
- If currently tracked, run:
  git rm --cached --ignore-unmatch django_smarthaul/.vscode/tasks.json

Commit 1: Backend migration and legacy removals

Stage backend additions and rewrites (one file per command):
git add django_smarthaul/manage.py
git add django_smarthaul/requirements.txt
git add django_smarthaul/config/__init__.py
git add django_smarthaul/config/asgi.py
git add django_smarthaul/config/settings.py
git add django_smarthaul/config/urls.py
git add django_smarthaul/config/wsgi.py
git add django_smarthaul/apps/__init__.py
git add django_smarthaul/apps/auth/__init__.py
git add django_smarthaul/apps/auth/admin.py
git add django_smarthaul/apps/auth/apps.py
git add django_smarthaul/apps/auth/authentication.py
git add django_smarthaul/apps/auth/models.py
git add django_smarthaul/apps/auth/serializers.py
git add django_smarthaul/apps/auth/urls.py
git add django_smarthaul/apps/auth/views.py
git add django_smarthaul/apps/auth/migrations/0001_initial.py
git add django_smarthaul/apps/bookings/__init__.py
git add django_smarthaul/apps/bookings/admin.py
git add django_smarthaul/apps/bookings/apps.py
git add django_smarthaul/apps/bookings/models.py
git add django_smarthaul/apps/bookings/serializers.py
git add django_smarthaul/apps/bookings/urls.py
git add django_smarthaul/apps/bookings/views.py
git add django_smarthaul/apps/bookings/migrations/0001_initial.py
git add django_smarthaul/apps/payments/__init__.py
git add django_smarthaul/apps/payments/admin.py
git add django_smarthaul/apps/payments/apps.py
git add django_smarthaul/apps/payments/models.py
git add django_smarthaul/apps/payments/serializers.py
git add django_smarthaul/apps/payments/urls.py
git add django_smarthaul/apps/payments/views.py
git add django_smarthaul/apps/payments/migrations/0001_initial.py
git add django_smarthaul/apps/providers/__init__.py
git add django_smarthaul/apps/providers/admin.py
git add django_smarthaul/apps/providers/apps.py
git add django_smarthaul/apps/providers/models.py
git add django_smarthaul/apps/providers/serializers.py
git add django_smarthaul/apps/providers/urls.py
git add django_smarthaul/apps/providers/views.py
git add django_smarthaul/apps/providers/migrations/0001_initial.py
git add django_smarthaul/apps/vendors/__init__.py
git add django_smarthaul/apps/vendors/admin.py
git add django_smarthaul/apps/vendors/apps.py
git add django_smarthaul/apps/vendors/models.py
git add django_smarthaul/apps/vendors/serializers.py
git add django_smarthaul/apps/vendors/urls.py
git add django_smarthaul/apps/vendors/views.py
git add django_smarthaul/apps/vendors/migrations/0001_initial.py
git add manage_admin.py
git add verify_deploy.py

Stage legacy removals:
git add app.py
git add auth.py
git add database.py
git add tests/test_smarthaul.py
git add requirements-free.txt

Commit:
git commit -m "migrate backend from FastAPI monolith to modular Django/DRF"

Commit 2: Deploy/runtime switch

Stage explicit files:
git add Procfile
git add render.yaml
git add requirements.txt

If runtime changed in your migration diff, add it too:
git add runtime.txt

Commit:
git commit -m "switch runtime and deploy config from Uvicorn to Gunicorn WSGI"

Commit 3: Documentation migration

Stage explicit files:
git add README.md
git add README_DEPLOY.md
git add DEPLOYMENT_COMPLETE.md
git add DEPLOYMENT_REPORT.md
git add DEPLOY_EXECUTION_STEPS.md
git add DEPLOY_NOW.md
git add IMPLEMENTATION_SUMMARY.md
git add PRODUCTION_DEPLOYMENT.md
git add smarthaul-prd.md

Commit:
git commit -m "update docs for Django/DRF architecture and deployment flow"

Verification after each commit
git show --name-only --oneline -1
git status --short

If terminal output is unreliable
- Use the Source Control panel to verify staged files before each commit.
- Keep batches small and verify immediately after each commit.

One-command execution option
- Script: commit_migration_safe.ps1
- Usage:
  powershell -ExecutionPolicy Bypass -File .\commit_migration_safe.ps1 -Step commit1
  powershell -ExecutionPolicy Bypass -File .\commit_migration_safe.ps1 -Step commit2
  powershell -ExecutionPolicy Bypass -File .\commit_migration_safe.ps1 -Step commit3

PowerShell script blocks (copy/paste)

Commit 1 script
```powershell
git rm --cached --ignore-unmatch django_smarthaul/.vscode/tasks.json
git add django_smarthaul/manage.py
git add django_smarthaul/requirements.txt
git add django_smarthaul/config/__init__.py
git add django_smarthaul/config/asgi.py
git add django_smarthaul/config/settings.py
git add django_smarthaul/config/urls.py
git add django_smarthaul/config/wsgi.py
git add django_smarthaul/apps/__init__.py
git add django_smarthaul/apps/auth/__init__.py
git add django_smarthaul/apps/auth/admin.py
git add django_smarthaul/apps/auth/apps.py
git add django_smarthaul/apps/auth/authentication.py
git add django_smarthaul/apps/auth/models.py
git add django_smarthaul/apps/auth/serializers.py
git add django_smarthaul/apps/auth/urls.py
git add django_smarthaul/apps/auth/views.py
git add django_smarthaul/apps/auth/migrations/0001_initial.py
git add django_smarthaul/apps/bookings/__init__.py
git add django_smarthaul/apps/bookings/admin.py
git add django_smarthaul/apps/bookings/apps.py
git add django_smarthaul/apps/bookings/models.py
git add django_smarthaul/apps/bookings/serializers.py
git add django_smarthaul/apps/bookings/urls.py
git add django_smarthaul/apps/bookings/views.py
git add django_smarthaul/apps/bookings/migrations/0001_initial.py
git add django_smarthaul/apps/payments/__init__.py
git add django_smarthaul/apps/payments/admin.py
git add django_smarthaul/apps/payments/apps.py
git add django_smarthaul/apps/payments/models.py
git add django_smarthaul/apps/payments/serializers.py
git add django_smarthaul/apps/payments/urls.py
git add django_smarthaul/apps/payments/views.py
git add django_smarthaul/apps/payments/migrations/0001_initial.py
git add django_smarthaul/apps/providers/__init__.py
git add django_smarthaul/apps/providers/admin.py
git add django_smarthaul/apps/providers/apps.py
git add django_smarthaul/apps/providers/models.py
git add django_smarthaul/apps/providers/serializers.py
git add django_smarthaul/apps/providers/urls.py
git add django_smarthaul/apps/providers/views.py
git add django_smarthaul/apps/providers/migrations/0001_initial.py
git add django_smarthaul/apps/vendors/__init__.py
git add django_smarthaul/apps/vendors/admin.py
git add django_smarthaul/apps/vendors/apps.py
git add django_smarthaul/apps/vendors/models.py
git add django_smarthaul/apps/vendors/serializers.py
git add django_smarthaul/apps/vendors/urls.py
git add django_smarthaul/apps/vendors/views.py
git add django_smarthaul/apps/vendors/migrations/0001_initial.py
git add manage_admin.py
git add verify_deploy.py
git add app.py
git add auth.py
git add database.py
git add tests/test_smarthaul.py
git add requirements-free.txt
git commit -m "migrate backend from FastAPI monolith to modular Django/DRF"
git show --name-only --oneline -1
git status --short
```

Commit 2 script
```powershell
git add Procfile
git add render.yaml
git add requirements.txt
git add runtime.txt
git commit -m "switch runtime and deploy config from Uvicorn to Gunicorn WSGI"
git show --name-only --oneline -1
git status --short
```

Commit 3 script
```powershell
git add README.md
git add README_DEPLOY.md
git add DEPLOYMENT_COMPLETE.md
git add DEPLOYMENT_REPORT.md
git add DEPLOY_EXECUTION_STEPS.md
git add DEPLOY_NOW.md
git add IMPLEMENTATION_SUMMARY.md
git add PRODUCTION_DEPLOYMENT.md
git add smarthaul-prd.md
git commit -m "update docs for Django/DRF architecture and deployment flow"
git show --name-only --oneline -1
git status --short
```

Safe mode scripts (checkpointed)

Safe mode Commit 1
```powershell
git rm --cached --ignore-unmatch django_smarthaul/.vscode/tasks.json

# Batch A: project core
git add django_smarthaul/manage.py
git add django_smarthaul/requirements.txt
git add django_smarthaul/config/__init__.py
git add django_smarthaul/config/asgi.py
git add django_smarthaul/config/settings.py
git add django_smarthaul/config/urls.py
git add django_smarthaul/config/wsgi.py
git status --short

# Batch B: auth app
git add django_smarthaul/apps/__init__.py
git add django_smarthaul/apps/auth/__init__.py
git add django_smarthaul/apps/auth/admin.py
git add django_smarthaul/apps/auth/apps.py
git add django_smarthaul/apps/auth/authentication.py
git add django_smarthaul/apps/auth/models.py
git add django_smarthaul/apps/auth/serializers.py
git add django_smarthaul/apps/auth/urls.py
git add django_smarthaul/apps/auth/views.py
git add django_smarthaul/apps/auth/migrations/0001_initial.py
git status --short

# Batch C: bookings app
git add django_smarthaul/apps/bookings/__init__.py
git add django_smarthaul/apps/bookings/admin.py
git add django_smarthaul/apps/bookings/apps.py
git add django_smarthaul/apps/bookings/models.py
git add django_smarthaul/apps/bookings/serializers.py
git add django_smarthaul/apps/bookings/urls.py
git add django_smarthaul/apps/bookings/views.py
git add django_smarthaul/apps/bookings/migrations/0001_initial.py
git status --short

# Batch D: payments app
git add django_smarthaul/apps/payments/__init__.py
git add django_smarthaul/apps/payments/admin.py
git add django_smarthaul/apps/payments/apps.py
git add django_smarthaul/apps/payments/models.py
git add django_smarthaul/apps/payments/serializers.py
git add django_smarthaul/apps/payments/urls.py
git add django_smarthaul/apps/payments/views.py
git add django_smarthaul/apps/payments/migrations/0001_initial.py
git status --short

# Batch E: providers and vendors apps
git add django_smarthaul/apps/providers/__init__.py
git add django_smarthaul/apps/providers/admin.py
git add django_smarthaul/apps/providers/apps.py
git add django_smarthaul/apps/providers/models.py
git add django_smarthaul/apps/providers/serializers.py
git add django_smarthaul/apps/providers/urls.py
git add django_smarthaul/apps/providers/views.py
git add django_smarthaul/apps/providers/migrations/0001_initial.py
git add django_smarthaul/apps/vendors/__init__.py
git add django_smarthaul/apps/vendors/admin.py
git add django_smarthaul/apps/vendors/apps.py
git add django_smarthaul/apps/vendors/models.py
git add django_smarthaul/apps/vendors/serializers.py
git add django_smarthaul/apps/vendors/urls.py
git add django_smarthaul/apps/vendors/views.py
git add django_smarthaul/apps/vendors/migrations/0001_initial.py
git status --short

# Batch F: migrated helpers + legacy removals
git add manage_admin.py
git add verify_deploy.py
git add app.py
git add auth.py
git add database.py
git add tests/test_smarthaul.py
git add requirements-free.txt
git status --short

git commit -m "migrate backend from FastAPI monolith to modular Django/DRF"
git show --name-only --oneline -1
git status --short
```

Safe mode Commit 2
```powershell
git add Procfile
git status --short
git add render.yaml
git status --short
git add requirements.txt
git status --short
git add runtime.txt
git status --short
git commit -m "switch runtime and deploy config from Uvicorn to Gunicorn WSGI"
git show --name-only --oneline -1
git status --short
```

Safe mode Commit 3
```powershell
git add README.md
git status --short
git add README_DEPLOY.md
git status --short
git add DEPLOYMENT_COMPLETE.md
git status --short
git add DEPLOYMENT_REPORT.md
git status --short
git add DEPLOY_EXECUTION_STEPS.md
git status --short
git add DEPLOY_NOW.md
git status --short
git add IMPLEMENTATION_SUMMARY.md
git status --short
git add PRODUCTION_DEPLOYMENT.md
git status --short
git add smarthaul-prd.md
git status --short
git commit -m "update docs for Django/DRF architecture and deployment flow"
git show --name-only --oneline -1
git status --short
```
