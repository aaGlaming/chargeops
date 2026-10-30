"""Seed the Step 11 authorization catalog and optionally create a user."""

from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import Settings
from app.services.auth import create_or_update_user, seed_authorization


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument("--display-name", default="ChargeOps User")
    parser.add_argument("--email")
    parser.add_argument("--role", action="append", dest="roles", default=[])
    args = parser.parse_args()

    settings = Settings.from_env()
    settings.validate()
    engine = create_engine(settings.mysql_dsn, future=True)
    with Session(engine) as session:
        role_ids = seed_authorization(session)
        if args.username or args.password:
            if not args.username or not args.password:
                raise SystemExit("--username and --password must be supplied together")
            user_id = create_or_update_user(
                session,
                username=args.username,
                password=args.password,
                display_name=args.display_name,
                email=args.email,
                role_codes=args.roles or ["SYSTEM_ADMIN"],
                settings=settings,
            )
            print({"authorization_seeded": True, "user_id": user_id, "username": args.username, "roles": args.roles or ["SYSTEM_ADMIN"]})
        else:
            print({"authorization_seeded": True, "roles": len(role_ids), "user_created": False})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
