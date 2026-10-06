"""Small constant-time API-key and bearer-token authentication boundary."""

from hashlib import sha256
from hmac import compare_digest

from fastapi import Request

from geoqc.interfaces.api.settings import ApiSettings


class AuthenticationResult:
    """Authentication decision without retaining the presented credential."""

    __slots__ = ("authenticated", "credential_present", "principal_key")

    def __init__(
        self, authenticated: bool, credential_present: bool, principal_key: str | None = None
    ) -> None:
        self.authenticated = authenticated
        self.credential_present = credential_present
        self.principal_key = principal_key


def authenticate(request: Request, settings: ApiSettings) -> AuthenticationResult:
    """Validate configured credentials with constant-time comparisons."""
    if not settings.authentication_enabled:
        return AuthenticationResult(True, False)
    api_key = request.headers.get("x-api-key")
    authorization = request.headers.get("authorization", "")
    bearer = authorization[7:].strip() if authorization.casefold().startswith("bearer ") else None
    presented = api_key is not None or bearer is not None or bool(authorization)
    key_valid = api_key is not None and any(
        compare_digest(api_key, expected) for expected in settings.api_keys
    )
    token_valid = bearer is not None and any(
        compare_digest(bearer, expected) for expected in settings.bearer_tokens
    )
    credential = api_key if key_valid else bearer if token_valid else None
    principal = (
        f"credential:{sha256(credential.encode('utf-8')).hexdigest()[:24]}"
        if credential is not None
        else None
    )
    return AuthenticationResult(key_valid or token_valid, presented, principal)
