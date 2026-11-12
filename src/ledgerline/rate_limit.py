import time
from collections import defaultdict

import redis
from fastapi import HTTPException, Request, status

from ledgerline.config import get_settings

_redis_client: redis.Redis | None = None
_memory_counters: dict[str, list[float]] = defaultdict(list)
_last_redis_failure: float = 0.0


def get_redis_client() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        settings = get_settings()
        kwargs: dict = {
            "decode_responses": True,
            "socket_connect_timeout": 1.0,
            "socket_timeout": 1.0,
            "retry_on_timeout": False,
        }
        if settings.redis_url.startswith("rediss://"):
            import ssl

            kwargs["ssl_cert_reqs"] = ssl.CERT_REQUIRED
        _redis_client = redis.Redis.from_url(settings.redis_url, **kwargs)
    return _redis_client


def check_redis_connection() -> tuple[bool, str]:
    try:
        client = get_redis_client()
        client.ping()
        return True, "connected"
    except Exception as exc:
        return False, str(exc)


def reset_rate_limit_state() -> None:
    global _last_redis_failure, _redis_client
    _last_redis_failure = 0.0
    _redis_client = None
    _memory_counters.clear()


def rate_limiter(max_requests: int | None = None, window_seconds: int = 60):
    async def _rate_limit_dependency(request: Request):
        global _last_redis_failure
        settings = get_settings()
        limit = max_requests or settings.rate_limit_per_minute

        client_host = request.client.host if request.client else "unknown"
        user_id = getattr(request.state, "user_id", None)
        key_identifier = f"rate_limit:{user_id or client_host}"
        current_time = time.time()
        is_production = settings.environment.lower() == "production"

        # Try Redis only if not currently in connection-failure cooldown
        if current_time - _last_redis_failure > 10.0:
            try:
                r = get_redis_client()
                pipe = r.pipeline(transaction=True)
                window_start = current_time - window_seconds
                pipe.zremrangebyscore(key_identifier, 0, window_start)
                pipe.zadd(key_identifier, {str(current_time): current_time})
                pipe.zcard(key_identifier)
                pipe.expire(key_identifier, window_seconds)
                results = pipe.execute()
                _last_redis_failure = 0.0
                request_count = results[2]

                if request_count > limit:
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail=f"Rate limit exceeded: maximum {limit} requests per {window_seconds}s.",
                        headers={"Retry-After": str(window_seconds)},
                    )
                return
            except HTTPException:
                raise
            except (redis.ConnectionError, redis.TimeoutError, redis.RedisError) as exc:
                _last_redis_failure = current_time
                if is_production:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail="Rate limiting backend unavailable: Production configuration requires a connected Redis instance and does not permit unshared in-memory rate limiting.",
                    ) from exc

        if is_production:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Rate limiting backend unavailable: Production configuration requires a connected Redis instance and does not permit unshared in-memory rate limiting.",
            )

        # In-memory sliding window fallback (strictly for development and automated test environments)
        timestamps = _memory_counters[key_identifier]
        window_start = current_time - window_seconds
        _memory_counters[key_identifier] = [t for t in timestamps if t > window_start]
        _memory_counters[key_identifier].append(current_time)

        if len(_memory_counters[key_identifier]) > limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded: maximum {limit} requests per {window_seconds}s.",
                headers={"Retry-After": str(window_seconds)},
            )

    return _rate_limit_dependency
