import pytest

from app.core.config import settings
from app.services import reference_map_service
from main import app


@pytest.fixture(autouse=True)
def _clear_reference_cache():
    reference_map_service._cache.clear()
    yield
    reference_map_service._cache.clear()


@pytest.fixture(autouse=True)
def _tests_without_redis_queue(monkeypatch):
    """CI и локальные тесты без Redis: вебхук обрабатывает Update синхронно."""
    monkeypatch.setattr(settings, "redis_url", "", raising=False)


@pytest.fixture(autouse=True)
def _reset_arq_pool_after_test():
    yield
    setattr(app.state, "arq_pool", None)
