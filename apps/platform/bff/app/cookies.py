"""Cookie сессии Платформы (контракт platform-bff.yaml, «Сессия»).

`rt_pf_session` — идентификатор сессии, `HttpOnly`; `rt_pf_csrf` — значение для заголовка
`X-CSRF-Token`, его читает скрипт SPA, поэтому не `HttpOnly`. Оба: `Secure` (кроме разработки
по http), `SameSite=Lax`, `Path=/`.
"""

from fastapi import Response

SESSION_COOKIE = "rt_pf_session"
CSRF_COOKIE = "rt_pf_csrf"
CSRF_HEADER = "X-CSRF-Token"


def set_session_cookies(
    response: Response, *, sid: str, csrf: str, max_age: int, secure: bool
) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        sid,
        max_age=max_age,
        path="/",
        secure=secure,
        httponly=True,
        samesite="lax",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        max_age=max_age,
        path="/",
        secure=secure,
        httponly=False,
        samesite="lax",
    )


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    response.delete_cookie(CSRF_COOKIE, path="/", secure=True, httponly=False, samesite="lax")
