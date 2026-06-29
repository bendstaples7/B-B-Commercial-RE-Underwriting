"""Load environment variables from the standard project .env locations.

Precedence (later wins):
  1. <project-root>/.env
  2. <backend>/.env
"""
from __future__ import annotations

import os
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _BACKEND_DIR.parent


def load_project_env() -> None:
    """Load .env files from project root and backend directory."""
    from dotenv import load_dotenv

    root_env = _PROJECT_ROOT / '.env'
    backend_env = _BACKEND_DIR / '.env'

    if root_env.is_file():
        load_dotenv(root_env)
    if backend_env.is_file():
        load_dotenv(backend_env, override=True)


def backend_dir() -> str:
    return str(_BACKEND_DIR)


def project_root() -> str:
    return str(_PROJECT_ROOT)
