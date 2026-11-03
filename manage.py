#!/usr/bin/env python
import os
import sys

if __name__ == "__main__":
    from config.process import prepare_process
    command = sys.argv[1] if len(sys.argv) > 1 else "help"
    role = {"runserver": "web", "run_ai_worker": "ai_worker", "run_scheduler": "scheduler", "test": "test"}.get(command, "management")
    prepare_process(role)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.test_settings" if command == "test" else "config.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
