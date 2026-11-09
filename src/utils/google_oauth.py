"""Read the public Google client ID from server-side OAuth credentials."""
import json
from pathlib import Path


def google_client_id(credentials_path):
    try:
        credentials = json.loads(Path(credentials_path).read_text(encoding="utf-8-sig"))
        client_id = credentials["web"]["client_id"]
        return client_id if isinstance(client_id, str) else ""
    except (OSError, ValueError, KeyError, TypeError):
        # Do not include credential file contents in errors or logs.
        return ""
