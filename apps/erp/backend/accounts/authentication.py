"""JWT-аутентификация сотрудников с версией токенов (FIX-11, S-6).

Обычная `JWTAuthentication` проверяет подпись, срок и активность пользователя. Добавлено одно условие:
claim `tv` access-токена должен равняться `CustomUser.token_version`. Отзыв доступа из CRM увеличивает
версию — уже выданные access-токены (до 30 минут жизни) отвечают 401 сразу, а не доживают срок.
"""

from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication

from accounts.services.tokens import token_version_of


class TokenVersionJWTAuthentication(JWTAuthentication):
    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        if token_version_of(validated_token) != user.token_version:
            raise AuthenticationFailed("TOKEN_REVOKED", code="token_revoked")
        return user
