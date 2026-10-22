"""CRM и ERP на respx: состояние входа, ротация refresh-токенов, выход (контракты CRM и ERP)."""

import base64
import json
from typing import Any

import httpx
import respx

from tests.consts import CRM_URL, ERP_URL
from tests.fakes import Clock

ERP_COOKIE = "refresh_token"
PASSWORD = "correct-horse"


def make_jwt(exp: float, jti: int) -> str:
    def seg(obj: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    return f"{seg({'alg': 'none'})}.{seg({'exp': int(exp), 'jti': jti})}.sig"


def profile(
    roles: list[str], *, access: tuple[str, ...] = ("crm", "erp"), user_id: int = 7
) -> dict[str, Any]:
    return {
        "id": user_id,
        "email": "ivan.test@example.org",
        "full_name": "Иван Тестов",
        "roles": ["viewer"],
        "is_active": True,
        "must_change_password": False,
        "platform_access": list(access),
        "platform_roles": roles,
        "position": "Менеджер по продажам",
        "language": "ru",
    }


class Backends:
    """Поведение CRM и ERP, которое тесты меняют на лету (поля и `*_status`)."""

    def __init__(self, router: respx.MockRouter, clock: Clock) -> None:
        self.router = router
        self.clock = clock
        self.router = router
        self.profile = profile(["MANAGER"])
        self.crm_access_ttl = 600
        self.crm_n = 0
        self.erp_n = 0
        self.crm_valid_access: set[str] = set()
        self.crm_valid_refresh: set[str] = set()
        self.erp_valid_refresh: set[str] = set()
        self.login_status = 200
        self.refresh_status = 200
        self.erp_refresh_status = 200
        self.exchange_status = 200
        self.sso_status = 200
        self.change_password_response: tuple[int, dict[str, Any]] = (204, {})
        self.me_unauthorized_once = False
        self.must_change = False
        self.crm_login = router.post(f"{CRM_URL}/api/v1/auth/login").mock(side_effect=self._login)
        self.crm_me = router.get(f"{CRM_URL}/api/v1/me").mock(side_effect=self._me)
        self.crm_refresh = router.post(f"{CRM_URL}/api/v1/auth/refresh").mock(
            side_effect=self._refresh
        )
        self.crm_logout = router.post(f"{CRM_URL}/api/v1/auth/logout").mock(
            return_value=httpx.Response(204)
        )
        self.crm_patch_me = router.patch(f"{CRM_URL}/api/v1/me").mock(side_effect=self._patch_me)
        self.crm_sso = router.post(f"{CRM_URL}/api/v1/auth/sso/token").mock(
            side_effect=self._sso_token
        )
        self.crm_change_password = router.post(f"{CRM_URL}/api/v1/auth/change-password").mock(
            side_effect=self._change_password
        )
        self.erp_exchange = router.post(f"{ERP_URL}/api/v1/auth/sso/exchange/").mock(
            side_effect=self._exchange
        )
        self.erp_refresh = router.post(f"{ERP_URL}/api/v1/auth/token/refresh/").mock(
            side_effect=self._erp_refresh
        )
        self.erp_logout = router.post(f"{ERP_URL}/api/v1/auth/logout/").mock(
            return_value=httpx.Response(205)
        )
        self.erp_ping = router.get(f"{ERP_URL}/api/v1/notifications/").mock(
            return_value=httpx.Response(200, json={"results": []})
        )

    # --- CRM ---
    def _crm_tokens(self) -> tuple[str, str]:
        self.crm_n += 1
        access, refresh = f"crm-access-{self.crm_n}", f"crm-refresh-{self.crm_n}"
        self.crm_valid_access.add(access)
        self.crm_valid_refresh.add(refresh)
        return access, refresh

    def _token_response(self) -> httpx.Response:
        access, refresh = self._crm_tokens()
        return httpx.Response(
            200,
            json={
                "access_token": access,
                "token_type": "bearer",
                "expires_in": self.crm_access_ttl,
                "must_change_password": self.must_change,
            },
            headers={
                "set-cookie": f"rt_refresh={refresh}; HttpOnly; Path=/api/v1/auth; SameSite=strict"
            },
        )

    def _login(self, request: httpx.Request) -> httpx.Response:
        if self.login_status != 200:
            return httpx.Response(
                self.login_status, json={"code": "auth_failed", "message": "x", "details": {}}
            )
        body = json.loads(request.content)
        if body["password"] != PASSWORD:
            return httpx.Response(
                401, json={"code": "auth_failed", "message": "invalid credentials", "details": {}}
            )
        return self._token_response()

    def _refresh(self, request: httpx.Request) -> httpx.Response:
        if self.refresh_status != 200:
            return httpx.Response(
                self.refresh_status, json={"code": "auth_failed", "message": "x", "details": {}}
            )
        cookie = request.headers.get("cookie", "")
        token = cookie.split("rt_refresh=")[-1].split(";")[0]
        if token not in self.crm_valid_refresh:
            return httpx.Response(
                401, json={"code": "auth_failed", "message": "reused", "details": {}}
            )
        self.crm_valid_refresh.discard(token)
        return self._token_response()

    def _bearer(self, request: httpx.Request) -> str:
        header: str = request.headers.get("authorization", "")
        return header.removeprefix("Bearer ")

    def _me(self, request: httpx.Request) -> httpx.Response:
        if self.me_unauthorized_once:
            self.me_unauthorized_once = False
            return httpx.Response(
                401, json={"code": "auth_failed", "message": "expired", "details": {}}
            )
        if self._bearer(request) not in self.crm_valid_access:
            return httpx.Response(
                401, json={"code": "auth_failed", "message": "bad token", "details": {}}
            )
        return httpx.Response(200, json={**self.profile, "must_change_password": self.must_change})

    def _patch_me(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if "language" in body:
            self.profile["language"] = body["language"]
        return httpx.Response(200, json=self.profile)

    def _sso_token(self, request: httpx.Request) -> httpx.Response:
        if self.sso_status != 200:
            return httpx.Response(
                self.sso_status, json={"code": "forbidden", "message": "x", "details": {}}
            )
        return httpx.Response(
            200, json={"token": "sso-token-1", "redirect_url": "http://erp.test/sso"}
        )

    def _change_password(self, request: httpx.Request) -> httpx.Response:
        status, body = self.change_password_response
        return httpx.Response(status, json=body) if body else httpx.Response(status)

    # --- ERP ---
    def _erp_session(self) -> tuple[str, str]:
        self.erp_n += 1
        refresh = f"erp-refresh-{self.erp_n}"
        self.erp_valid_refresh.add(refresh)
        return make_jwt(self.clock() + 300, self.erp_n), refresh

    def _exchange(self, request: httpx.Request) -> httpx.Response:
        if self.exchange_status != 200:
            return httpx.Response(self.exchange_status, json={"detail": "SSO_FAILED"})
        access, refresh = self._erp_session()
        return httpx.Response(
            200,
            json={"access_token": access, "expires_in": 300, "user": {"id": 1}},
            headers={
                "set-cookie": f"{ERP_COOKIE}={refresh}; HttpOnly; Path=/api/v1/auth/; SameSite=Lax"
            },
        )

    def _erp_refresh(self, request: httpx.Request) -> httpx.Response:
        if self.erp_refresh_status != 200:
            return httpx.Response(self.erp_refresh_status, json={"detail": "INVALID_REFRESH_TOKEN"})
        cookie = request.headers.get("cookie", "")
        token = cookie.split(f"{ERP_COOKIE}=")[-1].split(";")[0]
        if token not in self.erp_valid_refresh:
            return httpx.Response(401, json={"detail": "INVALID_REFRESH_TOKEN"})
        self.erp_valid_refresh.discard(token)
        access, refresh = self._erp_session()
        return httpx.Response(
            200,
            json={"access": access},
            headers={"set-cookie": f"{ERP_COOKIE}={refresh}; HttpOnly; Path=/api/v1/auth/"},
        )


def last_json(route: Any) -> Any:
    return json.loads(route.calls.last.request.content)
