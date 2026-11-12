from unittest.mock import MagicMock, patch

from fastapi import status
from fastapi.testclient import TestClient

from ledgerline.config import get_settings
from ledgerline.main import app
from ledgerline.rate_limit import reset_rate_limit_state


def test_production_rejects_silent_in_memory_fallback():
    """In production mode, if Redis is unavailable, requests must fail with 503 instead of silently using in-memory rate limiting."""
    reset_rate_limit_state()
    settings = get_settings()
    original_env = settings.environment
    try:
        settings.environment = "production"
        client = TestClient(app)

        with patch("ledgerline.rate_limit.get_redis_client") as mock_redis:
            import redis
            mock_client = MagicMock()
            mock_client.pipeline.side_effect = redis.ConnectionError("Redis connection refused")
            mock_redis.return_value = mock_client

            resp = client.post(
                "/auth/register",
                json={"email": "prod_rate_test@example.com", "password": "Password123!"},
            )
            assert resp.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
            assert "Rate limiting backend unavailable" in resp.json()["detail"]
    finally:
        settings.environment = original_env
        reset_rate_limit_state()


def test_development_allows_in_memory_fallback():
    """In development or testing mode, if Redis is unavailable, requests fall back to in-memory window."""
    reset_rate_limit_state()
    settings = get_settings()
    original_env = settings.environment
    try:
        settings.environment = "development"
        client = TestClient(app)

        with patch("ledgerline.rate_limit.get_redis_client") as mock_redis:
            import redis
            mock_client = MagicMock()
            mock_client.pipeline.side_effect = redis.ConnectionError("Redis down")
            mock_redis.return_value = mock_client

            responses = []
            for i in range(25):
                responses.append(
                    client.post(
                        "/auth/register",
                        json={"email": f"dev_rate_{i}@example.com", "password": "Password123!"},
                    )
                )

            statuses = [r.status_code for r in responses]
            assert 429 in statuses, f"Expected 429 in dev fallback statuses: {set(statuses)}"
    finally:
        settings.environment = original_env
        reset_rate_limit_state()


def test_multi_instance_redis_rate_limiting():
    """Verify that multiple application instances sharing the same Redis backend enforce shared limits."""
    reset_rate_limit_state()
    settings = get_settings()
    original_env = settings.environment
    try:
        settings.environment = "production"
        shared_store: dict[str, list[float]] = {}

        def create_mock_redis():
            mock_r = MagicMock()

            class MockPipeline:
                def __init__(self):
                    self.key = None

                def zremrangebyscore(self, key, min_s, max_s):
                    self.key = key
                    if key in shared_store:
                        shared_store[key] = [t for t in shared_store[key] if t > max_s]
                    return self

                def zadd(self, key, mapping):
                    self.key = key
                    ts = list(mapping.values())[0]
                    if key not in shared_store:
                        shared_store[key] = []
                    shared_store[key].append(ts)
                    return self

                def zcard(self, key):
                    return self

                def expire(self, key, seconds):
                    return self

                def execute(self):
                    count = len(shared_store.get(self.key, []))
                    return [0, 1, count, True]

            mock_r.pipeline.return_value = MockPipeline()
            return mock_r

        shared_mock = create_mock_redis()

        with patch("ledgerline.rate_limit.get_redis_client", return_value=shared_mock):
            client1 = TestClient(app)
            client2 = TestClient(app)

            # Instance 1 handles 15 requests (limit is 20)
            for i in range(15):
                r = client1.post(
                    "/auth/register",
                    json={"email": f"multi1_{i}@example.com", "password": "Password123!"},
                )
                assert r.status_code in (201, 400), f"Unexpected status: {r.status_code}"

            # Instance 2 handles 5 requests -> total 20 reached
            for i in range(5):
                r = client2.post(
                    "/auth/register",
                    json={"email": f"multi2_{i}@example.com", "password": "Password123!"},
                )
                assert r.status_code in (201, 400), f"Unexpected status: {r.status_code}"

            # 21st request on Instance 2 must be rejected with 429 due to shared state in Redis!
            r_exceeded = client2.post(
                "/auth/register",
                json={"email": "multi2_exceeded@example.com", "password": "Password123!"},
            )
            assert r_exceeded.status_code == status.HTTP_429_TOO_MANY_REQUESTS
            assert "Rate limit exceeded" in r_exceeded.json()["detail"]
    finally:
        settings.environment = original_env
        reset_rate_limit_state()
