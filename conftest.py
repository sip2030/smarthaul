import sys
import os

# Ensure the Django app directory is on sys.path so that
# 'config.settings' is importable when running pytest from the repo root.
DJANGO_DIR = os.path.join(os.path.dirname(__file__), "django_smarthaul")
if DJANGO_DIR not in sys.path:
    sys.path.insert(0, DJANGO_DIR)
