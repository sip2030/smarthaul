param(
    [ValidateSet('commit1','commit2','commit3')]
    [string]$Step = 'commit1'
)

$ErrorActionPreference = 'Stop'

function Run-Git {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Command
    )
    Write-Host "`n> $Command" -ForegroundColor Cyan
    Invoke-Expression $Command
}

function Checkpoint {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label
    )
    Write-Host "`n=== CHECKPOINT: $Label ===" -ForegroundColor Yellow
    Run-Git "git status --short"
}

function Commit-1 {
    Run-Git "git rm --cached --ignore-unmatch django_smarthaul/.vscode/tasks.json"

    # Batch A
    Run-Git "git add django_smarthaul/manage.py"
    Run-Git "git add django_smarthaul/requirements.txt"
    Run-Git "git add django_smarthaul/config/__init__.py"
    Run-Git "git add django_smarthaul/config/asgi.py"
    Run-Git "git add django_smarthaul/config/settings.py"
    Run-Git "git add django_smarthaul/config/urls.py"
    Run-Git "git add django_smarthaul/config/wsgi.py"
    Checkpoint "A"

    # Batch B
    Run-Git "git add django_smarthaul/apps/__init__.py"
    Run-Git "git add django_smarthaul/apps/auth/__init__.py"
    Run-Git "git add django_smarthaul/apps/auth/admin.py"
    Run-Git "git add django_smarthaul/apps/auth/apps.py"
    Run-Git "git add django_smarthaul/apps/auth/authentication.py"
    Run-Git "git add django_smarthaul/apps/auth/models.py"
    Run-Git "git add django_smarthaul/apps/auth/serializers.py"
    Run-Git "git add django_smarthaul/apps/auth/urls.py"
    Run-Git "git add django_smarthaul/apps/auth/views.py"
    Run-Git "git add django_smarthaul/apps/auth/migrations/0001_initial.py"
    Checkpoint "B"

    # Batch C
    Run-Git "git add django_smarthaul/apps/bookings/__init__.py"
    Run-Git "git add django_smarthaul/apps/bookings/admin.py"
    Run-Git "git add django_smarthaul/apps/bookings/apps.py"
    Run-Git "git add django_smarthaul/apps/bookings/models.py"
    Run-Git "git add django_smarthaul/apps/bookings/serializers.py"
    Run-Git "git add django_smarthaul/apps/bookings/urls.py"
    Run-Git "git add django_smarthaul/apps/bookings/views.py"
    Run-Git "git add django_smarthaul/apps/bookings/migrations/0001_initial.py"
    Checkpoint "C"

    # Batch D
    Run-Git "git add django_smarthaul/apps/payments/__init__.py"
    Run-Git "git add django_smarthaul/apps/payments/admin.py"
    Run-Git "git add django_smarthaul/apps/payments/apps.py"
    Run-Git "git add django_smarthaul/apps/payments/models.py"
    Run-Git "git add django_smarthaul/apps/payments/serializers.py"
    Run-Git "git add django_smarthaul/apps/payments/urls.py"
    Run-Git "git add django_smarthaul/apps/payments/views.py"
    Run-Git "git add django_smarthaul/apps/payments/migrations/0001_initial.py"
    Checkpoint "D"

    # Batch E
    Run-Git "git add django_smarthaul/apps/providers/__init__.py"
    Run-Git "git add django_smarthaul/apps/providers/admin.py"
    Run-Git "git add django_smarthaul/apps/providers/apps.py"
    Run-Git "git add django_smarthaul/apps/providers/models.py"
    Run-Git "git add django_smarthaul/apps/providers/serializers.py"
    Run-Git "git add django_smarthaul/apps/providers/urls.py"
    Run-Git "git add django_smarthaul/apps/providers/views.py"
    Run-Git "git add django_smarthaul/apps/providers/migrations/0001_initial.py"
    Run-Git "git add django_smarthaul/apps/vendors/__init__.py"
    Run-Git "git add django_smarthaul/apps/vendors/admin.py"
    Run-Git "git add django_smarthaul/apps/vendors/apps.py"
    Run-Git "git add django_smarthaul/apps/vendors/models.py"
    Run-Git "git add django_smarthaul/apps/vendors/serializers.py"
    Run-Git "git add django_smarthaul/apps/vendors/urls.py"
    Run-Git "git add django_smarthaul/apps/vendors/views.py"
    Run-Git "git add django_smarthaul/apps/vendors/migrations/0001_initial.py"
    Checkpoint "E"

    # Batch F
    Run-Git "git add manage_admin.py"
    Run-Git "git add verify_deploy.py"
    Run-Git "git add app.py"
    Run-Git "git add auth.py"
    Run-Git "git add database.py"
    Run-Git "git add tests/test_smarthaul.py"
    Run-Git "git add requirements-free.txt"
    Checkpoint "F"

    Run-Git "git commit -m 'migrate backend from FastAPI monolith to modular Django/DRF'"
    Run-Git "git show --name-only --oneline -1"
    Run-Git "git status --short"
}

function Commit-2 {
    Run-Git "git add Procfile"
    Checkpoint "2A"
    Run-Git "git add render.yaml"
    Checkpoint "2B"
    Run-Git "git add requirements.txt"
    Checkpoint "2C"
    Run-Git "git add runtime.txt"
    Checkpoint "2D"

    Run-Git "git commit -m 'switch runtime and deploy config from Uvicorn to Gunicorn WSGI'"
    Run-Git "git show --name-only --oneline -1"
    Run-Git "git status --short"
}

function Commit-3 {
    Run-Git "git add README.md"
    Checkpoint "3A"
    Run-Git "git add README_DEPLOY.md"
    Checkpoint "3B"
    Run-Git "git add DEPLOYMENT_COMPLETE.md"
    Checkpoint "3C"
    Run-Git "git add DEPLOYMENT_REPORT.md"
    Checkpoint "3D"
    Run-Git "git add DEPLOY_EXECUTION_STEPS.md"
    Checkpoint "3E"
    Run-Git "git add DEPLOY_NOW.md"
    Checkpoint "3F"
    Run-Git "git add IMPLEMENTATION_SUMMARY.md"
    Checkpoint "3G"
    Run-Git "git add PRODUCTION_DEPLOYMENT.md"
    Checkpoint "3H"
    Run-Git "git add smarthaul-prd.md"
    Checkpoint "3I"

    Run-Git "git commit -m 'update docs for Django/DRF architecture and deployment flow'"
    Run-Git "git show --name-only --oneline -1"
    Run-Git "git status --short"
}

switch ($Step) {
    'commit1' { Commit-1 }
    'commit2' { Commit-2 }
    'commit3' { Commit-3 }
    default { throw "Unknown step: $Step" }
}
