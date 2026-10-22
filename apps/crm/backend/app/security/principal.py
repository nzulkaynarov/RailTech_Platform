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
    # Роли Платформы (id): их правила casbin (`pr:<id>`) — единственные права сотрудника с ролями
    # (ADR-0012, R-1), см. `rbac_roles`.
    platform_role_ids: tuple[int, ...] = ()
    # Среди ролей Платформы есть системная «Администратор»: тогда действует и `admin` CRM.
    platform_admin: bool = False

    @property
    def rbac_roles(self) -> tuple[str, ...]:
        """Роли CRM для проверки прав. Сотрудник с ролями Платформы получает права только своих
        ролей (`pr:<id>`), плюс `admin`, если среди них системная «Администратор»; базовые
        `manager`/`viewer` — лишь совместимость старого поля `roles`, права не дают."""
        if not self.platform_role_ids:
            return self.roles
        return ("admin",) if self.platform_admin else ()

    @property
    def is_admin(self) -> bool:
        return "admin" in self.rbac_roles

    @property
    def actor(self) -> Actor:
        return Actor(self.user_id, "user", self.ip)

    @property
    def first_name(self) -> str:
        return self.full_name.split()[0] if self.full_name.strip() else ""
