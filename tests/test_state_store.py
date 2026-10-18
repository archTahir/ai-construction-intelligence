import tempfile
import unittest
from pathlib import Path

from construction_intelligence.state_store import create_default_state, load_state, save_state


class StateStoreTests(unittest.TestCase):
    def test_state_round_trip(self) -> None:
        """Save and reload state without losing values."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            state_path = Path(temporary_directory) / "data" / "state.json"
            state = create_default_state()
            state["project"]["name"] = "Test Project"
            save_state(state, state_path)
            loaded_state = load_state(state_path)
        self.assertEqual(loaded_state["project"]["name"], "Test Project")

    def test_second_save_creates_backup(self) -> None:
        """Create a backup before replacing an existing state file."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            state_path = Path(temporary_directory) / "data" / "state.json"
            state = create_default_state()
            save_state(state, state_path)
            state["project"]["name"] = "Updated"
            save_state(state, state_path)
            backups = list((state_path.parent / "backups").glob("*.json"))
        self.assertEqual(len(backups), 1)


if __name__ == "__main__":
    unittest.main()

