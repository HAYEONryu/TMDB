from .settings import *  # noqa: F403
from config.ai import AIConfig

TESTING = True
PROCESS_ROLE = "test"
AI_CONFIG = AIConfig(reason="AI_TEST_ONLY")
