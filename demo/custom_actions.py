"""Example custom-actions module.

ccwalk.yaml points at this file via `custom_actions:`; the runner imports
it and calls register(actions) before the tour starts. This is where
app-specific verbs live -- composites of the generic actions, or anything
needing app knowledge (the predecessor system had send_chat_message /
wait_for_response here, for a chat app).
"""


def act_add_note(rt, step, text: str, **_):
    """Composite: fill the demo app's note input and submit it."""
    rt.page.fill("[data-testid=note-input]", text)
    rt.page.click("[data-testid=note-add]")
    return {"added": text}


def register(actions: dict) -> None:
    actions["add_note"] = act_add_note
