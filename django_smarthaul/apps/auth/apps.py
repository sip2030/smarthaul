"""Auth app configuration."""
from django.apps import AppConfig


class AuthConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.auth'
    verbose_name = 'Authentication'
    label = 'smarthaul_auth'

