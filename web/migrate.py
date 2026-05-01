"""One-shot migrations run from run.sh before gunicorn starts.

This lives outside app.py so multi-worker races can't occur: run.sh invokes
this script once, then spawns gunicorn, and each worker reads the
post-migration state.

Exits 0 even on failure so a migration bug cannot block the container from
coming up — app.py is expected to handle both pre- and post-migration states
gracefully.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time


SECRET_KEY_PATH = '/var/lib/bastion/secret_key'
SECRET_KEY_OLD_PATH = '/var/lib/bastion/secret_key.old'
USERS_DB_PATH = '/var/lib/bastion/users.db'

# 32 bytes, hex-encoded, is 64 characters. Anything shorter is a pre-L1 key
# (older containers generated 24 bytes / 48 hex chars).
REQUIRED_HEX_LEN = 64

# Sessions expire after 30 minutes (PERMANENT_SESSION_LIFETIME). Keep the
# fallback key at least double that, so no outstanding session can be signed
# with a retired key we no longer load.
FALLBACK_GRACE_SECONDS = 3600


def _log(msg: str) -> None:
    print(f'[migrate] {msg}', file=sys.stderr, flush=True)


def rotate_secret_key() -> None:
    """Rotate an under-sized Flask SECRET_KEY in place, with a fallback window.

    - If no key file exists, do nothing (app.py will generate a 32-byte key).
    - If the key is already 32 bytes, only clean up a stale fallback.
    - If the key is shorter, move it aside to SECRET_KEY_OLD_PATH (atomic via
      os.replace) and write a fresh 32-byte key. app.py will load both, signing
      new sessions with the fresh key and still validating old ones until they
      expire.
    """
    if not os.path.exists(SECRET_KEY_PATH):
        return

    try:
        with open(SECRET_KEY_PATH, 'r') as f:
            current = f.read().strip()
    except OSError as exc:
        _log(f'could not read SECRET_KEY: {exc}')
        return

    if len(current) >= REQUIRED_HEX_LEN:
        # Already rotated or fresh. Retire any stale fallback past its window.
        if os.path.exists(SECRET_KEY_OLD_PATH):
            try:
                age = time.time() - os.path.getmtime(SECRET_KEY_OLD_PATH)
            except OSError:
                return
            if age > FALLBACK_GRACE_SECONDS:
                try:
                    os.remove(SECRET_KEY_OLD_PATH)
                    _log('retired stale SECRET_KEY fallback')
                except OSError as exc:
                    _log(f'could not remove stale fallback: {exc}')
        return

    new_key = os.urandom(32).hex()
    try:
        # os.replace is atomic on POSIX; overwrites any pre-existing fallback.
        os.replace(SECRET_KEY_PATH, SECRET_KEY_OLD_PATH)
        os.chmod(SECRET_KEY_OLD_PATH, 0o600)
        # Write new key to a temp name, chmod, then rename into place so a
        # reader never observes a world-readable or half-written key file.
        tmp_path = SECRET_KEY_PATH + '.new'
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, new_key.encode('ascii'))
        finally:
            os.close(fd)
        os.replace(tmp_path, SECRET_KEY_PATH)
    except OSError as exc:
        _log(f'rotation failed mid-flight: {exc}')
        return

    _log(
        f'rotated SECRET_KEY from {len(current) * 4}-bit to 256-bit; '
        'previous key retained as fallback for grace period'
    )


def add_force_password_change_column() -> None:
    """Add User.force_password_change column to an existing users.db.

    Idempotent: skips when DB/table absent (fresh install — db.create_all() in
    app.py will create with the column already in the model) or when the
    column already exists.
    """
    if not os.path.exists(USERS_DB_PATH):
        return
    try:
        con = sqlite3.connect(USERS_DB_PATH)
        try:
            cur = con.cursor()
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='user'"
            )
            if not cur.fetchone():
                return
            cur.execute("PRAGMA table_info(user)")
            cols = {row[1] for row in cur.fetchall()}
            if 'force_password_change' in cols:
                return
            cur.execute(
                "ALTER TABLE user ADD COLUMN force_password_change "
                "BOOLEAN NOT NULL DEFAULT 0"
            )
            con.commit()
            _log('added User.force_password_change column')
        finally:
            con.close()
    except Exception as exc:  # noqa: BLE001 — must not block container start
        _log(f'force_password_change migration failed: {exc!r}')


def main() -> None:
    try:
        rotate_secret_key()
    except Exception as exc:  # noqa: BLE001 — must not block container start
        _log(f'unexpected error: {exc!r}')
    try:
        add_force_password_change_column()
    except Exception as exc:  # noqa: BLE001 — must not block container start
        _log(f'unexpected error: {exc!r}')


if __name__ == '__main__':
    main()
    sys.exit(0)
