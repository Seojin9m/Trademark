"""One-shot: hand the pre-existing SnapTrade user over to a Supabase user.

Before the multi-user migration, SnapTrade was registered with a single,
fixed user id (``trademark-user``) and its credentials lived in
``backend/data/snaptrade_state.json``. After the migration, every user gets
their own ``brokerage_connections`` row keyed by the Supabase UUID.

SnapTrade Personal Keys allow only one registered user per Client ID, so we
cannot just register a new SnapTrade user for the existing Supabase account
-- the API returns code 1012. Instead, we *claim* the existing SnapTrade
user by inserting a brokerage_connections row that points at the legacy
SnapTrade credentials. The Wealthsimple OAuth grant the user already
authorized stays intact: no re-connect needed.

Usage::

    cd backend
    python -m scripts.claim_legacy_snaptrade <supabase_user_email>
    # or, to target a specific Supabase user UUID directly:
    python -m scripts.claim_legacy_snaptrade --user-id <uuid>

After it runs, the JSON file is renamed to ``snaptrade_state.json.claimed``
so future runs don't accidentally double-claim.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import settings
from src.db.postgres import get_pg_connection


LEGACY_PATH = settings.paths.data_dir / "snaptrade_state.json"


def _resolve_user(arg_email: str | None, arg_user_id: str | None) -> tuple[str, str]:
    con = get_pg_connection(role="direct")
    try:
        cur = con.cursor()
        if arg_user_id:
            cur.execute("SELECT id, email FROM auth.users WHERE id = %s::uuid", (arg_user_id,))
        elif arg_email:
            cur.execute("SELECT id, email FROM auth.users WHERE email = %s", (arg_email,))
        else:
            cur.execute("SELECT id, email FROM auth.users ORDER BY created_at DESC LIMIT 2")
            rows = cur.fetchall()
            if len(rows) > 1:
                raise SystemExit(
                    "Multiple Supabase users exist; pass --email or --user-id to disambiguate.\n"
                    "Candidates:\n" + "\n".join(f"  {r[0]}  {r[1]}" for r in rows)
                )
            if not rows:
                raise SystemExit("No Supabase users found; sign up first, then re-run this script.")
            return str(rows[0][0]), rows[0][1]
        row = cur.fetchone()
        if not row:
            raise SystemExit("No matching Supabase user found.")
        return str(row[0]), row[1]
    finally:
        con.close()


def _read_legacy_state() -> tuple[str, str]:
    if not LEGACY_PATH.exists():
        raise SystemExit(f"No legacy SnapTrade state at {LEGACY_PATH}. Nothing to claim.")
    state = json.loads(LEGACY_PATH.read_text())
    snap_uid = state.get("user_id") or state.get("userId")
    snap_secret = state.get("user_secret") or state.get("userSecret")
    if not snap_uid or not snap_secret:
        raise SystemExit("Legacy snaptrade_state.json is missing user_id / user_secret.")
    return snap_uid, snap_secret


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--email", help="Supabase user email to attach to")
    p.add_argument("--user-id", help="Supabase user UUID to attach to (overrides --email)")
    p.add_argument("--broker", default="WEALTHSIMPLETRADE")
    args = p.parse_args()

    user_id, email = _resolve_user(args.email, args.user_id)
    snap_uid, snap_secret = _read_legacy_state()

    print(f"Claiming SnapTrade user {snap_uid!r} for Supabase user {email} ({user_id})")

    con = get_pg_connection(role="direct")
    try:
        cur = con.cursor()
        cur.execute(
            """
            INSERT INTO brokerage_connections
                (user_id, broker, snaptrade_user_id, snaptrade_user_secret, status)
            VALUES (%s::uuid, %s, %s, %s, 'active')
            ON CONFLICT (user_id, broker) DO UPDATE
                SET snaptrade_user_id = EXCLUDED.snaptrade_user_id,
                    snaptrade_user_secret = EXCLUDED.snaptrade_user_secret,
                    status = 'active'
            """,
            (user_id, args.broker, snap_uid, snap_secret),
        )
        con.commit()
    finally:
        con.close()

    # Rename the JSON file so we can't accidentally re-claim later.
    archived = LEGACY_PATH.with_suffix(".json.claimed")
    LEGACY_PATH.rename(archived)
    print(f"Inserted brokerage_connections row.")
    print(f"Archived legacy state file: {archived}")
    print()
    print("Next: in the AuthFlow, the user should now skip the brokerage step")
    print("(set has_brokerage=true via Supabase Dashboard → Auth → Users → metadata),")
    print("OR re-trigger sync via the brokerage page.")


if __name__ == "__main__":
    main()
