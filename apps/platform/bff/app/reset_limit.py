"""Лимит «Забыли пароль?» (W15-H6): запросов в час на IP и на адрес; сверх лимита — 429.

Запрос считается всегда, существует учётная запись или нет: по скорости ответа и по счётчику
сотрудников перечислять нельзя. Фиксированное окно в Redis, как у `LoginLimiter`.
"""

import hashlib

from redis.asyncio import Redis

from app.errors import PlatformError

WINDOW_SECONDS = 3600


class HourlyLimiter:
    def __init__(self, redis: Redis, prefix: str, per_hour: int) -> None:
        self.redis = redis
        self.prefix = prefix
        self.per_hour = per_hour

    async def _hit(self, key: str) -> tuple[int, int]:
        await self.redis.set(key, 0, ex=WINDOW_SECONDS, nx=True)
        count = int(await self.redis.incr(key))
        ttl = int(await self.redis.ttl(key))
        if ttl < 0:  # ключ без срока заблокировал бы запросы навсегда
            await self.redis.expire(key, WINDOW_SECONDS)
            ttl = WINDOW_SECONDS
        return count, ttl

    async def check(self, ip: str, subject: str | None = None) -> None:
        """Записать запрос; сверх лимита по IP или по адресу — 429 с `Retry-After`."""
        keys = [f"rl:{self.prefix}:ip:{ip}"]
        if subject is not None:
            digest = hashlib.sha256(subject.strip().lower().encode()).hexdigest()[:32]
            keys.append(f"rl:{self.prefix}:subject:{digest}")
        retry_after = 0
        for key in keys:
            count, ttl = await self._hit(key)
            if count > self.per_hour:
                retry_after = max(retry_after, ttl)
        if retry_after:
            raise PlatformError(
                "TOO_MANY_REQUESTS",
                "Слишком много запросов. Повторите позже.",
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )
