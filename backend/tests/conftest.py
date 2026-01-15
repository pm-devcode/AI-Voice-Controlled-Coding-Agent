import pytest
import asyncio
from fastapi import FastAPI
from backend.src.main import app


@pytest.fixture
def test_app():
    return app


@pytest.fixture
def event_loop():
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()
