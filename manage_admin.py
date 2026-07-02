import argparse
import os
import sys

from database import create_admin_user, init_db


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