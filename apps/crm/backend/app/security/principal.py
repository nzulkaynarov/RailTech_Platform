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

    @property
    def rbac_roles(self) -> tuple[str, ...]:
        """Роли CRM для проверки прав. Сотрудник с ролями Платформы получает права только своих
        ролей (`pr:<id>`), в том числе системная «Администратор» — права раздела `admin` каталога,
        а не `admin` CRM (`*:*`, решение R3-D-2): лиды, клиенты и сделки ей не положены. Базовые
        роли CRM (`admin`/`manager`/`viewer`) — лишь совместимость старого поля `roles`, права не
        дают."""
        return () if self.platform_role_ids else self.roles

    @property
    def is_admin(self) -> bool:
        """Объектные исключения админа (чужой лид, закрытая сделка) — только у `admin` CRM без ролей
        Платформы; у сотрудника с ролями Платформы их нет (R3-D-2)."""
        return "admin" in self.rbac_roles

    @property
    def actor(self) -> Actor:
        return Actor(self.user_id, "user", self.ip)

    @property
    def first_name(self) -> str:
        return self.full_name.split()[0] if self.full_name.strip() else ""
