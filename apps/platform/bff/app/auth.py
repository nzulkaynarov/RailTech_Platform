"""Вход, выход и вызовы бэкендов от имени сотрудника (02-architecture.md §3).

Вход: CRM login (refresh-cookie CRM перехватывается) -> CRM `/me` -> при доступе к ERP: CRM
`sso/token` -> ERP `sso/exchange` (refresh-cookie ERP перехватывается) -> запись в Redis. Дальше
каждый вызов бэкенда идёт через `AuthService.call`: просроченный access обновляется refresh-токеном
под блокировкой сессии (одна попытка); провал обновления удаляет сессию и даёт 401
`SESSION_EXPIRED`.
"""

import asyncio
import base64
import hashlib
import json
from typing import Any

import httpx
import structlog
from redis.asyncio import Redis

from app.clients import CrmClient, ErpClient
from app.clients.base import Backend, BackendUnavailableError, cookie_value
from app.clients.crm_models import SsoTokenResponse
from app.config import Settings
from app.errors import (
    PlatformError,
    backend_code,
    backend_reason,
    backend_unavailable,
    from_backend,
    session_expired,
)
from app.session import (
    BackendTokens,
    Language,
    SessionData,
    SessionRole,
    SessionStore,
    new_secret,
    now,
)

log = structlog.get_logger()

# Обновлять access за столько секунд до истечения.
ACCESS_SKEW_SECONDS = 30
# Профиль CRM (роли, доступ, блокировка) перечитывается не чаще раза в минуту.
PROFILE_TTL_SECONDS = 60
# Не переподключать ERP чаще, если он не ответил.
ERP_RETRY_SECONDS = 15
RATE_WINDOW_SECONDS = 60
# Статусы, после которых refresh-токен считается мёртвым (сотрудник отключён, токен отозван);
# остальные ответы (400, 404, 422, 429, 5xx) — сбой бэкенда, сессия остаётся.
_DEAD_TOKEN_STATUSES = frozenset({401, 403})


class ErpConnectError(Exception):
    """ERP не выдал сессию по SSO (не 200, нет refresh-cookie, неожиданный ответ)."""


def jwt_expiry(token: str) -> float | None:
    """Поле `exp` JWT без проверки подписи: срок нужен только для планирования обновления."""
    try:
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return float(claims["exp"])
    except (IndexError, ValueError, KeyError, TypeError):
        return None


def client_ip(forwarded_for: str | None, peer: str | None) -> str:
    """Адрес клиента: последний элемент `X-Forwarded-For` (его добавляет Caddy), иначе сокет."""
    if forwarded_for:
        last = forwarded_for.split(",")[-1].strip()
        if last:
            return last
    return peer or "unknown"


class LoginLimiter:
    """Не больше N попыток входа в минуту — отдельно на IP и на e-mail (фиксированное окно)."""

    def __init__(self, redis: Redis, per_minute: int) -> None:
        self.redis = redis
        self.per_minute = per_minute

    async def _hit(self, key: str) -> tuple[int, int]:
        await self.redis.set(key, 0, ex=RATE_WINDOW_SECONDS, nx=True)
        count = int(await self.redis.incr(key))
        ttl = int(await self.redis.ttl(key))
        if ttl < 0:
            # Ключ без срока заблокировал бы вход навсегда (сбой между записью и сроком).
            await self.redis.expire(key, RATE_WINDOW_SECONDS)
            ttl = RATE_WINDOW_SECONDS
        return count, ttl

    async def check(self, ip: str, email: str) -> None:
        digest = hashlib.sha256(email.strip().lower().encode()).hexdigest()[:32]
        retry_after = 0
        for key in (f"rl:login:ip:{ip}", f"rl:login:email:{digest}"):
            count, ttl = await self._hit(key)
            if count > self.per_minute:
                retry_after = max(retry_after, ttl)
        if retry_after:
            raise PlatformError(
                "TOO_MANY_REQUESTS",
                "Слишком много попыток входа. Повторите через минуту.",
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )


def _expect(resp: httpx.Response, source: Backend, *, ok: int = 200) -> httpx.Response:
    if resp.status_code != ok:
        raise from_backend(source, resp)
    return resp


class AuthService:
    def __init__(self, redis: Redis, crm: CrmClient, erp: ErpClient, settings: Settings) -> None:
        self.redis = redis
        self.store = SessionStore(redis)
        self.crm = crm
        self.erp = erp
        self.settings = settings

    # --- вход -------------------------------------------------------------------------------------

    async def login(self, email: str, password: str) -> tuple[str, SessionData]:
        try:
            resp = await self.crm.login(email, password)
        except BackendUnavailableError as exc:
            raise backend_unavailable("crm", exc.reason) from exc
        if resp.status_code in (401, 403):
            raise PlatformError(
                "INVALID_CREDENTIALS",
                "Неверный e-mail или пароль.",
                status_code=401,
                source="crm",
                details={"backend_code": backend_code(resp)} if backend_code(resp) else None,
            )
        _expect(resp, "crm")
        tokens = CrmClient.tokens(resp)
        if tokens.refresh is None:
            raise backend_unavailable("crm", "no_refresh_cookie")
        crm_tokens = BackendTokens(
            access=tokens.access,
            access_exp=now() + tokens.expires_in,
            refresh=tokens.refresh,
        )
        try:
            return await self._open_session(crm_tokens, tokens.must_change_password)
        except BaseException:
            # Входа не вышло (нет ролей Платформы, сбой): CRM-сессию не оставляем висеть.
            await self.crm.logout(crm_tokens.refresh)
            raise

    async def _open_session(
        self, crm_tokens: BackendTokens, must_change_password: bool
    ) -> tuple[str, SessionData]:
        try:
            resp = await self.crm.me(crm_tokens.access)
        except BackendUnavailableError as exc:
            raise backend_unavailable("crm", exc.reason) from exc
        profile: dict[str, Any] = _expect(resp, "crm").json()
        roles = roles_of(profile)
        if not roles:
            raise PlatformError(
                "NO_PLATFORM_ROLE",
                "Вам не назначена роль Платформы. Обратитесь к администратору.",
                status_code=403,
            )
        access = list(profile.get("platform_access") or ["crm"])
        created = now()
        data = SessionData(
            csrf=new_secret(),
            created_at=created,
            expires_at=created + self.settings.session_ttl_hours * 3600,
            user_id=int(profile["id"]),
            email=str(profile["email"]),
            name=str(profile["full_name"]),
            position=profile.get("position") or None,
            language=_language(profile),
            roles=roles,
            platform_access=access,
            must_change_password=must_change_password or bool(profile.get("must_change_password")),
            profile_checked_at=created,
            crm=crm_tokens,
            erp_state="not_applicable",
        )
        if "erp" in access:
            erp_tokens = await self._try_connect_erp(crm_tokens.access)
            data.erp = erp_tokens
            data.erp_state = "ok" if erp_tokens else "unavailable"
            if erp_tokens is None:
                data.erp_next_try = created + ERP_RETRY_SECONDS
        sid = await self.store.create(data)
        return sid, data

    async def _try_connect_erp(self, crm_access: str) -> BackendTokens | None:
        """SSO CRM -> ERP. Сбой ERP не мешает работе с CRM: источник помечается недоступным."""
        try:
            return await self._connect_erp(crm_access)
        except (BackendUnavailableError, ErpConnectError) as exc:
            log.warning("erp_connect_failed", error=str(exc))
            return None

    async def _connect_erp(self, crm_access: str) -> BackendTokens:
        sso = await self.crm.sso_token(crm_access)
        if sso.status_code != 200:
            raise ErpConnectError(f"crm sso/token: HTTP {sso.status_code}")
        try:
            sso_token = SsoTokenResponse.model_validate(sso.json()).token
        except (ValueError, KeyError, TypeError) as exc:
            raise ErpConnectError("crm sso/token: unexpected body") from exc
        exchange = await self.erp.sso_exchange(sso_token)
        if exchange.status_code != 200:
            raise ErpConnectError(f"erp sso/exchange: HTTP {exchange.status_code}")
        refresh = cookie_value(exchange, self.erp.refresh_cookie)
        try:
            body = exchange.json()
            access = str(body["access_token"])
            expires_in = float(body.get("expires_in") or 300)
        except (ValueError, KeyError, TypeError) as exc:
            raise ErpConnectError("erp sso/exchange: unexpected body") from exc
        if refresh is None:
            raise ErpConnectError("erp sso/exchange: no refresh cookie")
        return BackendTokens(
            access=access, access_exp=jwt_expiry(access) or now() + expires_in, refresh=refresh
        )

    # --- выход ------------------------------------------------------------------------------------

    async def logout(self, sid: str) -> None:
        """Удалить сессию и погасить токены CRM и ERP; идемпотентно, сбои бэкендов не мешают."""
        async with self.store.lock(sid):
            data = await self.store.get(sid)
            await self.store.delete(sid)
        if data is not None:
            await self.teardown(data)

    async def teardown(self, data: SessionData) -> None:
        jobs = [self.crm.logout(data.crm.refresh)]
        if data.erp is not None:
            jobs.append(self._erp_logout(data.erp))
        await asyncio.gather(*jobs)

    async def _erp_logout(self, tokens: BackendTokens) -> None:
        access, refresh = tokens.access, tokens.refresh
        if tokens.access_exp - now() <= ACCESS_SKEW_SECONDS:
            # Выход в ERP требует живой access: берём новый по refresh-токену.
            try:
                resp = await self.erp.refresh(refresh)
                if resp.status_code == 200:
                    access = str(resp.json()["access"])
                    refresh = cookie_value(resp, self.erp.refresh_cookie) or refresh
            except (BackendUnavailableError, ValueError, KeyError, TypeError):
                return
        await self.erp.logout(access, refresh)

    # --- токены и вызовы бэкендов -----------------------------------------------------------------

    async def _load(self, sid: str) -> SessionData:
        data = await self.store.get(sid)
        if data is None:
            raise session_expired()
        return data

    @staticmethod
    def _stale(tokens: BackendTokens, rejected: str | None) -> bool:
        if rejected is not None and tokens.access == rejected:
            return True
        return tokens.access_exp - now() <= ACCESS_SKEW_SECONDS

    async def _prepare(
        self, sid: str, backend: Backend, rejected: str | None = None
    ) -> SessionData:
        """Сессия с живым access нужного бэкенда: под блокировкой обновить его, если пора.

        `rejected` — access, который бэкенд только что отверг: если за время ожидания блокировки его
        уже обновил другой запрос, повторно не обновляем.
        """
        async with self.store.lock(sid):
            data = await self._load(sid)
            if backend == "crm":
                if self._stale(data.crm, rejected):
                    await self._refresh(sid, data, "crm")
                return data
            if data.erp_state == "not_applicable":
                raise PlatformError(
                    "FORBIDDEN",
                    "Нет доступа к ERP.",
                    status_code=403,
                    source="erp",
                    details={"reason": "erp_not_granted"},
                )
            if data.erp is None:
                await self._reconnect_erp(sid, data)
            elif self._stale(data.erp, rejected):
                await self._refresh(sid, data, "erp")
            return data

    async def _reconnect_erp(self, sid: str, data: SessionData) -> None:
        if now() < data.erp_next_try:
            raise backend_unavailable("erp", "reconnect_cooldown")
        if self._stale(data.crm, None):
            await self._refresh(sid, data, "crm")
        tokens = await self._try_connect_erp(data.crm.access)
        if tokens is None:
            data.erp_next_try = now() + ERP_RETRY_SECONDS
            await self.store.save(sid, data)
            raise backend_unavailable("erp", "sso_failed")
        data.erp, data.erp_state = tokens, "ok"
        await self.store.save(sid, data)

    async def _refresh(self, sid: str, data: SessionData, backend: Backend) -> None:
        """Одна попытка обновить access refresh-токеном (под блокировкой сессии)."""
        tokens = data.crm if backend == "crm" else data.erp
        assert tokens is not None  # noqa: S101 — вызывается только при наличии токенов
        try:
            if backend == "crm":
                resp = await self.crm.refresh(tokens.refresh)
            else:
                resp = await self.erp.refresh(tokens.refresh)
        except BackendUnavailableError as exc:
            raise backend_unavailable(backend, exc.reason) from exc
        if resp.status_code in _DEAD_TOKEN_STATUSES:
            # Сотрудник отключён или токен отозван: сессия Платформы умирает вместе с ними.
            log.info("session_refresh_rejected", backend=backend, status=resp.status_code)
            await self.store.delete(sid)
            raise session_expired()
        if resp.status_code != 200:
            raise backend_unavailable(backend, f"HTTP {resp.status_code}")
        try:
            if backend == "crm":
                fresh = CrmClient.tokens(resp)
                access, lifetime = fresh.access, float(fresh.expires_in)
                rotated = fresh.refresh
            else:
                access = str(resp.json()["access"])
                lifetime = 300.0
                rotated = cookie_value(resp, self.erp.refresh_cookie)
        except (ValueError, KeyError, TypeError) as exc:
            raise backend_unavailable(backend, "bad_refresh_response") from exc
        tokens.access = access
        tokens.access_exp = (jwt_expiry(access) if backend == "erp" else None) or now() + lifetime
        tokens.refresh = rotated or tokens.refresh
        await self.store.save(sid, data)

    async def _send(
        self,
        backend: Backend,
        tokens: BackendTokens,
        method: str,
        path: str,
        json_body: Any,
        params: dict[str, Any] | None,
    ) -> httpx.Response:
        client = self.crm if backend == "crm" else self.erp
        try:
            return await client.send(
                method, path, access=tokens.access, json=json_body, params=params
            )
        except BackendUnavailableError as exc:
            raise backend_unavailable(backend, exc.reason) from exc

    async def call(
        self,
        sid: str,
        backend: Backend,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Вызов CRM или ERP с токеном сотрудника. 2xx и 4xx бэкенда возвращаются как есть.

        Просроченный access обновляется заранее; если бэкенд всё же ответил 401 — одно обновление и
        повтор. Не помогло — сессия удаляется, 401 `SESSION_EXPIRED`.
        """
        data = await self._prepare(sid, backend)
        tokens = data.crm if backend == "crm" else data.erp
        assert tokens is not None  # noqa: S101 — _prepare гарантирует токены
        resp = await self._send(backend, tokens, method, path, json, params)
        if resp.status_code != 401:
            return resp
        data = await self._prepare(sid, backend, rejected=tokens.access)
        tokens = data.crm if backend == "crm" else data.erp
        assert tokens is not None  # noqa: S101
        resp = await self._send(backend, tokens, method, path, json, params)
        if resp.status_code == 401:
            await self.store.delete(sid)
            raise session_expired()
        return resp

    # --- профиль и пароль -------------------------------------------------------------------------

    async def sync_profile(self, sid: str, data: SessionData) -> SessionData:
        """Перечитать профиль CRM (роли, доступ, блокировка), если снимок старше минуты.

        CRM недоступен — работаем по снимку. Ролей Платформы больше нет — сессия закрывается.
        """
        if now() - data.profile_checked_at < PROFILE_TTL_SECONDS:
            return data
        try:
            resp = await self.call(sid, "crm", "GET", "/api/v1/me")
        except PlatformError as exc:
            if exc.status_code == 503:
                return data
            raise
        if resp.status_code != 200:
            log.warning("profile_sync_failed", status=resp.status_code)
            return data
        profile: dict[str, Any] = resp.json()
        if not roles_of(profile):
            await self.logout(sid)
            raise PlatformError(
                "NO_PLATFORM_ROLE",
                "Вам не назначена роль Платформы. Обратитесь к администратору.",
                status_code=403,
                clear_session=True,
            )

        def apply(d: SessionData) -> None:
            _apply_profile(d, profile)

        updated = await self.store.update(sid, apply)
        if updated is None:
            raise session_expired()
        return updated

    async def set_language(self, sid: str, language: Language) -> None:
        """Язык хранит CRM (`PATCH /api/v1/me`); в сессии — копия до следующего чтения профиля."""
        resp = await self.call(sid, "crm", "PATCH", "/api/v1/me", json={"language": language})
        if resp.status_code != 200:
            raise from_backend("crm", resp)
        await self.store.update(sid, lambda d: setattr(d, "language", language))

    async def change_password(self, sid: str, current: str, new: str) -> None:
        resp = await self.call(
            sid,
            "crm",
            "POST",
            "/api/v1/auth/change-password",
            json={"current_password": current, "new_password": new},
        )
        if resp.status_code != 204:
            if resp.status_code == 422 and backend_reason(resp) == "wrong_password":
                raise PlatformError(
                    "WRONG_PASSWORD",
                    "Текущий пароль указан неверно.",
                    status_code=422,
                    source="crm",
                    details={"fields": ["current_password"]},
                )
            err = from_backend("crm", resp)
            if resp.status_code == 422:
                err.body.details = {**(err.body.details or {}), "fields": _failed_fields(resp)}
            raise err
        await self.store.update(sid, _clear_must_change)


def _clear_must_change(data: SessionData) -> None:
    data.must_change_password = False


def _failed_fields(resp: httpx.Response) -> list[str]:
    try:
        field = resp.json()["details"]["field"]
    except (ValueError, KeyError, TypeError):
        return []
    return [field] if isinstance(field, str) else []


def _language(profile: dict[str, Any]) -> Language:
    """Язык интерфейса из профиля CRM (`users.language`, CRM-01b); нет или неизвестен — `ru`."""
    value = profile.get("language")
    return value if value in ("ru", "uz", "en") else "ru"


def roles_of(profile: dict[str, Any]) -> list[SessionRole]:
    """Роли Платформы из `/me` CRM (`platform_role_refs` с матрицами, R-2). Битая запись не роняет
    вход: такая роль пропускается (права всё равно решает CRM)."""
    roles: list[SessionRole] = []
    for raw in profile.get("platform_role_refs") or []:
        if not isinstance(raw, dict):
            continue
        try:
            roles.append(SessionRole.model_validate(raw))
        except ValueError:
            log.warning("platform_role_unreadable")
    return roles


def _apply_profile(data: SessionData, profile: dict[str, Any]) -> None:
    roles = roles_of(profile)
    access = list(profile.get("platform_access") or ["crm"])
    data.name = str(profile.get("full_name") or data.name)
    data.position = profile.get("position") or None
    data.language = _language(profile)
    data.roles = roles
    data.platform_access = access
    data.must_change_password = bool(profile.get("must_change_password"))
    data.profile_checked_at = now()
    if data.active_role not in {r.id for r in roles}:
        data.active_role = None
    if "erp" not in access:
        data.erp, data.erp_state = None, "not_applicable"
    elif data.erp_state == "not_applicable":
        data.erp_state, data.erp_next_try = "unavailable", 0.0
