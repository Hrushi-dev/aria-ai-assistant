# -*- coding: utf-8 -*-
"""
Aria Obsidian Bridge
--------------------
Provides utility functions and tool-level helpers for the Obsidian Vault.
Delegates core memory storage directly to obsidian_memory.py (SQLite has been eliminated).
"""

import os
import json
import logging
from pathlib import Path
from typing import Optional, List, Dict

import obsidian_memory as om

logger = logging.getLogger("obsidian_bridge")


def get_vault_path() -> Path:
    """Return active Obsidian vault path."""
    return om.get_vault_path()


def export_all_memory(vault_path: Optional[Path] = None) -> Dict[str, int]:
    """Verify and refresh the Obsidian Vault structure and return item counts."""
    if not vault_path:
        vault_path = get_vault_path()

    vault_path.mkdir(parents=True, exist_ok=True)
    om._ensure_vault_structure()

    facts = om.get_all_facts()
    todos = om.get_todos("all")
    reminders = om.get_reminders(active_only=False)

    return {
        "facts": len(facts),
        "todos": len(todos),
        "reminders": len(reminders),
        "vault_path": str(vault_path),
    }


def search_vault(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """Search markdown files in the Obsidian vault."""
    return om.search_vault(query, max_results=max_results)


def read_note(note_rel_path: str) -> Optional[str]:
    """Read full content of a note from the Obsidian vault."""
    return om.read_note(note_rel_path)


# Compatibility stubs for any residual callers
def sync_message_to_obsidian(user_id: int, role: str, message: str):
    pass

def sync_fact_to_obsidian(key: str, value: Optional[str]):
    pass

def sync_trigger_to_obsidian(phrase: str, payload: str):
    pass
