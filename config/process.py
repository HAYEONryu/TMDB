import os

AI_ROLES = {"web", "ai_worker"}


def prepare_process(role):
    """Called before Django setup, independent of user-supplied request data."""
    if role not in {"web", "ai_worker", "scheduler", "management", "test"}:
        raise ValueError("Unknown server process role")
    os.environ["TM_PROCESS_ROLE"] = role
    if role not in AI_ROLES:
        for key in list(os.environ):
            if key.startswith("AI_"):
                os.environ.pop(key)
