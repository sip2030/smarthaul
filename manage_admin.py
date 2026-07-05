import argparse
import os
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DJANGO_DIR = BASE_DIR / "django_smarthaul"
if str(DJANGO_DIR) not in sys.path:
    sys.path.insert(0, str(DJANGO_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402


def init_db() -> None:
    django.setup()


def create_admin_user(name: str, email: str, password: str, update_existing: bool = False) -> tuple[bool, str]:
    User = get_user_model()
    if not email:
        return False, "Admin email is required."
    if not password:
        return False, "Admin password is required."

    user = User.objects.filter(email=email).first()
    if user is None:
        user = User(
            username=email,
            email=email,
            first_name=name,
            role="admin",
            is_staff=True,
            is_superuser=True,
        )
        user.set_password(password)
        user.save()
        return True, f"Created admin account for {email}."

    if update_existing:
        user.username = user.username or email
        user.first_name = name
        user.role = "admin"
        user.is_staff = True
        user.is_superuser = True
        user.set_password(password)
        user.save()
        return True, f"Updated admin account for {email}."

    return False, f"Admin account already exists for {email}. Use --update-existing to refresh it."


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create or update a SmartHaul admin account.")
    parser.add_argument("--name", default=os.getenv("BOOTSTRAP_ADMIN_NAME", "SmartHaul Admin"), help="Admin display name")
    parser.add_argument("--email", default=os.getenv("BOOTSTRAP_ADMIN_EMAIL", ""), help="Admin email address")
    parser.add_argument("--password", default=os.getenv("BOOTSTRAP_ADMIN_PASSWORD", ""), help="Admin password")
    parser.add_argument(
        "--update-existing",
        action="store_true",
        help="Update the password and ensure admin role if the email already exists",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    init_db()
    created, message = create_admin_user(args.name, args.email, args.password, update_existing=args.update_existing)
    print(message)
    return 0 if created else 1


if __name__ == "__main__":
    raise SystemExit(main())