def format_scope_card(plan: dict) -> str:
    goal = plan.get("goal_description", "Unknown Goal")
    steps = plan.get("steps", [])
    scope = plan.get("scope_boundary", {})
    
    text = f"📋 **Scope Contract Proposed**\n\n"
    text += f"**Goal:** {goal}\n\n"
    text += "**Execution Steps:**\n"
    for i, step in enumerate(steps, 1):
        text += f"{i}. [{step.get('tool')}] {step.get('description')}\n"
    
    text += "\n**Scope Boundaries:**\n"
    read_paths = scope.get("allowed_read_paths", [])
    write_paths = scope.get("allowed_write_paths", [])
    external = scope.get("external_actions", [])
    
    text += "👀 Read: " + (", ".join(read_paths) if read_paths else "None") + "\n"
    text += "✍️ Write: " + (", ".join(write_paths) if write_paths else "None") + "\n"
    text += "🌐 External: " + (", ".join(external) if external else "None") + "\n"
    
    text += "\nDo you approve this execution plan?"
    return text

def build_approval_keyboard(goal_id: str):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    keyboard = [
        [
            InlineKeyboardButton("✅ Approve Scope", callback_data=f"scope_approve:{goal_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"scope_reject:{goal_id}")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)
