"""Текущий пользователь запроса (после проверки токена и загрузки из БД)."""

from dataclasses import dataclass

from app.security.audit import Actor


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: int
    full_name: str
    roles: tuple[str, ...]
    must_change_password: bool = False
    ip: str | None = None

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles

    @property
    def actor(self) -> Actor:
        return Actor(self.user_id, "user", self.ip)

    @property
    def first_name(self) -> str:
        return self.full_name.split()[0] if self.full_name.strip() else ""
