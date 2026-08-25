from pathlib import Path

WAYPOINT_HOME = Path.home() / ".waypoint"
CURRENT_SESSION_FILE = WAYPOINT_HOME / "current_session.json"
MEMORY_DIR = WAYPOINT_HOME / "memory"
MEMORY_INDEX_FILE = MEMORY_DIR / "MEMORY.md"

# Component 10 (spec)
MAX_TOKEN_BUDGET = 250_000
COMPACT_TRIGGER = 200_000
KEEP_RECENT = 10

# Component 3 (spec)
DEFAULT_HOTKEY = "ctrl+alt"

# Component 9 (spec)
ANNOTATION_FADE_SECONDS = 4

# Open item in spec: session-end idle threshold that triggers memory
# distillation (Component 12). Defaulting to 10 minutes; override via
# panel settings once Task 18 exists.
SESSION_END_IDLE_SECONDS = 600
