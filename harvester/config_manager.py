"""
config_manager.py - Manages journal configurations and user settings.

Handles loading/saving journal databases, preset lists, and user parameters
such as save paths, Zotero credentials, and institutional login info.
"""

import json
import os
from typing import Dict, List, Optional, Any


class JournalConfigManager:
    """
    Manages the journal configuration database and preset lists.

    Loads journal metadata (ISSN, publisher, URLs) from JSON config files
    and provides methods to query journals by list membership or field.
    """

    # Default paths for config files (relative to package root)
    DEFAULT_CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config")
    DEFAULT_JOURNALS_FILE = os.path.join(DEFAULT_CONFIG_DIR, "journals.json")
    DEFAULT_PRESETS_FILE = os.path.join(DEFAULT_CONFIG_DIR, "presets.json")

    def __init__(
        self,
        journals_file: Optional[str] = None,
        presets_file: Optional[str] = None,
    ):
        """
        Initialize the config manager with optional custom config file paths.

        Args:
            journals_file: Path to the journals JSON file. Defaults to config/journals.json.
            presets_file: Path to the presets JSON file. Defaults to config/presets.json.
        """
        self.journals_file = journals_file or self.DEFAULT_JOURNALS_FILE
        self.presets_file = presets_file or self.DEFAULT_PRESETS_FILE
        self._journals: Dict[str, Dict] = {}  # keyed by journal id
        self._presets: Dict[str, Dict] = {}
        self._load()

    # ------------------------------------------------------------------
    # Loading / saving
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load journals and presets from JSON config files."""
        if os.path.exists(self.journals_file):
            with open(self.journals_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            for journal in data.get("journals", []):
                self._journals[journal["id"]] = journal
        else:
            print(f"[WARNING] Journals file not found: {self.journals_file}")

        if os.path.exists(self.presets_file):
            with open(self.presets_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._presets = data.get("presets", {})
        else:
            print(f"[WARNING] Presets file not found: {self.presets_file}")

    def save_journals(self) -> None:
        """Persist the current journal database back to the JSON file."""
        os.makedirs(os.path.dirname(self.journals_file), exist_ok=True)
        with open(self.journals_file, "w", encoding="utf-8") as f:
            json.dump({"journals": list(self._journals.values())}, f, indent=2, ensure_ascii=False)

    def save_presets(self) -> None:
        """Persist the current presets back to the JSON file."""
        os.makedirs(os.path.dirname(self.presets_file), exist_ok=True)
        with open(self.presets_file, "w", encoding="utf-8") as f:
            json.dump({"presets": self._presets}, f, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Journal access
    # ------------------------------------------------------------------

    def get_all_journals(self) -> List[Dict]:
        """Return all configured journals as a list."""
        return list(self._journals.values())

    def get_journal(self, journal_id: str) -> Optional[Dict]:
        """
        Return journal metadata for a given journal ID.

        Args:
            journal_id: The short ID of the journal (e.g. 'ms', 'jf').

        Returns:
            Journal metadata dict, or None if not found.
        """
        return self._journals.get(journal_id)

    def get_journals_by_list(self, list_name: str) -> List[Dict]:
        """
        Return all journals that belong to the specified list.

        Args:
            list_name: One of 'utd24', 'ft50', 'abs4', or any custom list name.

        Returns:
            List of journal metadata dicts.
        """
        return [j for j in self._journals.values() if list_name in j.get("lists", [])]

    def get_journals_by_preset(self, preset_id: str) -> List[Dict]:
        """
        Return journals for a named preset (e.g. 'marketing_utd').

        Args:
            preset_id: Key from presets.json.

        Returns:
            List of journal metadata dicts.
        """
        preset = self._presets.get(preset_id)
        if not preset:
            raise ValueError(f"Preset '{preset_id}' not found.")
        ids = preset.get("journal_ids", [])
        return [self._journals[jid] for jid in ids if jid in self._journals]

    def get_journals_by_ids(self, journal_ids: List[str]) -> List[Dict]:
        """
        Return journal metadata for a list of journal IDs.

        Args:
            journal_ids: List of journal ID strings.

        Returns:
            List of journal metadata dicts (skips unknown IDs).
        """
        return [self._journals[jid] for jid in journal_ids if jid in self._journals]

    def get_all_presets(self) -> Dict[str, Dict]:
        """Return the full presets dictionary."""
        return self._presets

    # ------------------------------------------------------------------
    # Journal management
    # ------------------------------------------------------------------

    def add_journal(self, journal: Dict) -> None:
        """
        Add or update a journal entry.

        Args:
            journal: Dict with at minimum 'id', 'name', 'issn_print' keys.
        """
        if "id" not in journal:
            raise ValueError("Journal must have an 'id' field.")
        self._journals[journal["id"]] = journal

    def remove_journal(self, journal_id: str) -> bool:
        """
        Remove a journal by ID.

        Args:
            journal_id: ID of the journal to remove.

        Returns:
            True if removed, False if not found.
        """
        if journal_id in self._journals:
            del self._journals[journal_id]
            return True
        return False

    def add_preset(self, preset_id: str, name: str, description: str, journal_ids: List[str]) -> None:
        """
        Add or replace a custom preset.

        Args:
            preset_id: Unique key for the preset.
            name: Human-readable name.
            description: Description of the preset.
            journal_ids: List of journal IDs in this preset.
        """
        self._presets[preset_id] = {
            "name": name,
            "description": description,
            "journal_ids": journal_ids,
        }


class UserSettings:
    """
    Manages persistent user settings such as save path, Zotero credentials,
    institutional login info, and Unpaywall email.

    Settings are stored as a JSON file in the user's home directory.
    """

    DEFAULT_SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".paper_harvester_settings.json")

    def __init__(self, settings_file: Optional[str] = None):
        """
        Initialize user settings, loading from file if it exists.

        Args:
            settings_file: Path to settings JSON file. Defaults to ~/.paper_harvester_settings.json.
        """
        self.settings_file = settings_file or self.DEFAULT_SETTINGS_FILE
        self._settings: Dict[str, Any] = self._defaults()
        self._load()

    def _defaults(self) -> Dict[str, Any]:
        """Return factory-default settings."""
        return {
            "save_path": os.path.join(os.path.expanduser("~"), "PaperHarvester"),
            "unpaywall_email": "",
            "zotero_enabled": False,
            "zotero_library_type": "user",  # 'user' or 'group'
            "zotero_library_id": "",
            "zotero_api_key": "",
            "institutional_login_enabled": False,
            "institutional_org": "",
            "institutional_username": "",
            "institutional_password": "",
            "google_scholar_fallback": True,
        }

    def _load(self) -> None:
        """Load settings from file, merging with defaults for missing keys."""
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                self._settings.update(saved)
            except (json.JSONDecodeError, OSError):
                pass  # Use defaults on error

    def save(self) -> None:
        """Persist current settings to file."""
        os.makedirs(os.path.dirname(self.settings_file) or ".", exist_ok=True)
        with open(self.settings_file, "w", encoding="utf-8") as f:
            json.dump(self._settings, f, indent=2, ensure_ascii=False)

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a setting value by key."""
        return self._settings.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a setting value and persist to file."""
        self._settings[key] = value
        self.save()

    def get_all(self) -> Dict[str, Any]:
        """Return a copy of all settings."""
        return dict(self._settings)

    def display(self) -> None:
        """Print current settings to the console (masks passwords)."""
        print("\n--- Current Settings ---")
        for key, value in self._settings.items():
            if "password" in key.lower() and value:
                display_value = "***"
            elif "api_key" in key.lower() and value:
                display_value = value[:4] + "***"
            else:
                display_value = value
            print(f"  {key}: {display_value}")
        print("------------------------\n")
