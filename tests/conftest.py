"""Pytest configuration."""

import os

# Ensure test environment
os.environ.setdefault("SF_CLICK_ID_SECRET", "test-secret-key-for-testing")
os.environ.setdefault("SF_DATABASE_URL", "sqlite+aiosqlite:///test.db")
os.environ.setdefault("SF_DEBUG", "true")
