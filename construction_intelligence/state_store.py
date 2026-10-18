import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path


STATE_VERSION = 1


def current_timestamp() -> str:
    """Return the current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def create_default_state() -> dict:
    """Create a new empty application state."""
    return {
        "state_version": STATE_VERSION,
        "project": {
            "project_id": "P01",
            "name": "Construction Intelligence Project",
            "created_at": current_timestamp(),
        },
        "documents": {},
        "issues": {},
        "review_queue": [],
        "runs": [],
        "settings": {
            "model": os.getenv("GEMINI_MODEL", "gemini-flash-latest"),
            "analysis_depth": "detailed",
            "enabled_specialists": [
                "engineering",
                "contract_commercial",
                "programme_procurement",
                "quality_compliance",
            ],
            "require_review_for_uncertain_matches": True,
            "maximum_meetings_per_run": 20,
        },
    }


def ensure_state_directories(state_path: str | Path) -> None:
    """Create the data and backup directories used by the state store."""
    resolved_state_path = Path(state_path)
    resolved_state_path.parent.mkdir(parents=True, exist_ok=True)
    (resolved_state_path.parent / "backups").mkdir(parents=True, exist_ok=True)


def load_state(state_path: str | Path) -> dict:
    """Load the application state or create a new state when none exists."""
    resolved_state_path = Path(state_path)
    ensure_state_directories(resolved_state_path)
    if not resolved_state_path.exists():
        return create_default_state()
    with resolved_state_path.open("r", encoding="utf-8") as state_file:
        loaded_state = json.load(state_file)
    if loaded_state.get("state_version") != STATE_VERSION:
        raise ValueError("The state file version is not supported by this application.")
    return loaded_state


def create_state_backup(state_path: str | Path) -> Path | None:
    """Create a timestamped backup of an existing state file."""
    resolved_state_path = Path(state_path)
    if not resolved_state_path.exists():
        return None
    backup_timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup_path = resolved_state_path.parent / "backups" / f"state-{backup_timestamp}.json"
    shutil.copy2(resolved_state_path, backup_path)
    return backup_path


def save_state(state: dict, state_path: str | Path, create_backup: bool = True) -> None:
    """Validate and atomically save application state."""
    resolved_state_path = Path(state_path)
    ensure_state_directories(resolved_state_path)
    serialized_state = json.dumps(state, indent=2, ensure_ascii=False)
    json.loads(serialized_state)
    if create_backup:
        create_state_backup(resolved_state_path)
    temporary_file_descriptor, temporary_file_name = tempfile.mkstemp(
        prefix="state-",
        suffix=".json",
        dir=resolved_state_path.parent,
    )
    try:
        with os.fdopen(temporary_file_descriptor, "w", encoding="utf-8") as temporary_file:
            temporary_file.write(serialized_state)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_file_name, resolved_state_path)
    finally:
        if Path(temporary_file_name).exists():
            Path(temporary_file_name).unlink()

