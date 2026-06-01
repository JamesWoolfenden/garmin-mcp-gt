"""
Helper to load/save Garmin tokens from the DB and create a Garmin client.

Tokens are stored as a JSON dict mapping filename → file content.
On each use we write to a temp directory, create the Garmin client,
make the API call, then read back any refreshed tokens.
"""

import json
import shutil
import tempfile
from pathlib import Path

from garminconnect import Garmin

from db import load_garmin_tokens, save_garmin_tokens


class GarminSession:
    """Context manager that creates a Garmin client from stored tokens."""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self._tmpdir: str | None = None
        self.client: Garmin | None = None

    def __enter__(self) -> Garmin:
        tokens_json = load_garmin_tokens(self.user_id)
        if not tokens_json:
            raise RuntimeError(
                "No Garmin tokens found for this user. "
                "Run garmin-upload-tokens to set up your Garmin connection."
            )

        self._tmpdir = tempfile.mkdtemp(prefix="garmin_")
        tokens = json.loads(tokens_json)
        for filename, content in tokens.items():
            (Path(self._tmpdir) / filename).write_text(
                content if isinstance(content, str) else json.dumps(content)
            )

        self.client = Garmin()
        self.client.login(self._tmpdir)
        return self.client

    def __exit__(self, *_):
        if self._tmpdir:
            # Read back tokens (they may have been refreshed)
            updated = {}
            for f in Path(self._tmpdir).iterdir():
                try:
                    updated[f.name] = json.loads(f.read_text())
                except Exception:
                    updated[f.name] = f.read_text()
            if updated:
                save_garmin_tokens(self.user_id, json.dumps(updated))
            shutil.rmtree(self._tmpdir, ignore_errors=True)
