import os

AI_ROLES = {"web", "ai_worker"}


def load_app_environment(path, environment=None):
    from dotenv import dotenv_values
    environment = os.environ if environment is None else environment
    for name, value in dotenv_values(path, interpolate=False).items():
        if value is not None and not name.startswith("AI_") and name not in {"TM_PROCESS_ROLE", "DJANGO_SETTINGS_MODULE"}:
            environment.setdefault(name, value)


def prepare_process(role):
    """Called before Django setup, independent of user-supplied request data."""
    if role not in {"web", "ai_worker", "scheduler", "management", "test"}:
        raise ValueError("Unknown server process role")
    os.environ["TM_PROCESS_ROLE"] = role
    if role not in AI_ROLES:
        for key in list(os.environ):
            if key.startswith("AI_"):
                os.environ.pop(key)
