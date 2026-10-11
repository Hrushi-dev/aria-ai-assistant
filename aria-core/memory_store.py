# -*- coding: utf-8 -*-
"""
Aria Memory Store
-----------------
Obsidian-Native Memory Store.
SQLite has been completely replaced by direct Markdown notes in the Obsidian Vault (D:/HERMES/AriaVault).
Provides zero-latency cached facts, persistent daily logs, and full personal assistant capabilities:
- Todos list
- Reminders & schedule
- Profile facts
- Quick notes & knowledge vault search
"""

from obsidian_memory import (
    get_fact,
    set_fact,
    get_all_facts,
    add_message,
    get_recent_history,
    log_audit,
    set_trigger,
    get_triggers,
    get_engine_metric,
    update_engine_metric,
    set_agent_plan,
    get_agent_plan,
    # Personal Assistant features
    add_todo,
    get_todos,
    complete_todo,
    remove_todo,
    add_reminder,
    get_reminders,
    dismiss_reminder,
    save_note,
    read_note,
    search_vault,
    get_vault_path,
)