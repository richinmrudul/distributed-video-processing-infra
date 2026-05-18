from app.services import distributed_lock
from app.services.distributed_lock import RedisDistributedLock


class SharedRedis:
    values: dict[str, str] = {}
    fail = False

    def __init__(self, *args, **kwargs) -> None:
        self.closed = False

    def set(self, key: str, value: str, *, nx: bool, ex: int):
        if self.fail:
            raise RuntimeError("redis down")
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def eval(self, script: str, numkeys: int, key: str, value: str):
        if self.fail:
            raise RuntimeError("redis down")
        if self.values.get(key) == value:
            del self.values[key]
            return 1
        return 0

    def close(self) -> None:
        self.closed = True


def _patch_redis(monkeypatch):
    SharedRedis.values = {}
    SharedRedis.fail = False
    monkeypatch.setattr(distributed_lock.Redis, "from_url", lambda *args, **kwargs: SharedRedis())


def test_acquire_succeeds_when_key_absent(monkeypatch):
    _patch_redis(monkeypatch)
    lock = RedisDistributedLock(key="lock", ttl_seconds=10, acquire_timeout_seconds=0)

    assert lock.acquire()
    assert lock.acquired


def test_second_lock_cannot_acquire_same_key(monkeypatch):
    _patch_redis(monkeypatch)
    first = RedisDistributedLock(key="lock", ttl_seconds=10, acquire_timeout_seconds=0)
    second = RedisDistributedLock(key="lock", ttl_seconds=10, acquire_timeout_seconds=0)

    assert first.acquire()
    assert not second.acquire()


def test_release_succeeds_only_for_owner(monkeypatch):
    _patch_redis(monkeypatch)
    owner = RedisDistributedLock(key="lock", ttl_seconds=10, acquire_timeout_seconds=0)
    non_owner = RedisDistributedLock(key="lock", ttl_seconds=10, acquire_timeout_seconds=0)

    assert owner.acquire()
    non_owner._redis = SharedRedis()
    non_owner.acquired = True
    assert not non_owner.release()
    assert SharedRedis.values["lock"] == owner.value
    assert owner.release()
    assert "lock" not in SharedRedis.values


def test_release_after_failed_acquire_is_safe(monkeypatch):
    _patch_redis(monkeypatch)
    first = RedisDistributedLock(key="lock", ttl_seconds=10, acquire_timeout_seconds=0)
    second = RedisDistributedLock(key="lock", ttl_seconds=10, acquire_timeout_seconds=0)

    assert first.acquire()
    assert not second.acquire()
    assert not second.release()


def test_redis_exception_causes_acquire_and_release_false(monkeypatch):
    _patch_redis(monkeypatch)
    SharedRedis.fail = True
    lock = RedisDistributedLock(key="lock", ttl_seconds=10, acquire_timeout_seconds=0)

    assert not lock.acquire()
    assert lock.last_error
    lock._redis = SharedRedis()
    lock.acquired = True
    assert not lock.release()
