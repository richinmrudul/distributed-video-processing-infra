import time
import uuid

from redis import Redis

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

_RELEASE_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
else
    return 0
end
"""


class RedisDistributedLock:
    """Single-Redis lock for local coordination.

    This is suitable for this local/single-Redis architecture. Multi-Redis production
    locking has deeper tradeoffs; this intentionally does not implement Redlock.
    """

    def __init__(
        self,
        *,
        key: str,
        ttl_seconds: int,
        acquire_timeout_seconds: int,
        redis_url: str | None = None,
    ) -> None:
        self.key = key
        self.ttl_seconds = ttl_seconds
        self.acquire_timeout_seconds = acquire_timeout_seconds
        self.value = str(uuid.uuid4())
        self._redis_url = redis_url or settings.redis_url
        self._redis: Redis | None = None
        self.acquired = False
        self.last_error: str | None = None

    def acquire(self) -> bool:
        deadline = time.monotonic() + max(0, self.acquire_timeout_seconds)
        self._redis = Redis.from_url(self._redis_url, decode_responses=True)
        try:
            while True:
                result = self._redis.set(self.key, self.value, nx=True, ex=self.ttl_seconds)
                if result:
                    self.acquired = True
                    return True
                if time.monotonic() >= deadline:
                    return False
                time.sleep(0.1)
        except Exception as exc:
            self.last_error = str(exc)
            log.warning("redis_lock_acquire_failed", lock_key=self.key, error=str(exc))
            return False

    def release(self) -> bool:
        if not self._redis or not self.acquired:
            return False
        try:
            released = bool(self._redis.eval(_RELEASE_SCRIPT, 1, self.key, self.value))
            self.acquired = False
            return released
        except Exception as exc:
            self.last_error = str(exc)
            log.warning("redis_lock_release_failed", lock_key=self.key, error=str(exc))
            return False
        finally:
            self.close()

    def close(self) -> None:
        if self._redis is not None:
            try:
                self._redis.close()
            except Exception:
                pass
            self._redis = None
