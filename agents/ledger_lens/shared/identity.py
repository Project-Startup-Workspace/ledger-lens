"""Who is signed in, from Firebase Authentication, and the account changes an organisation
admin makes. Roles are kept in the directory; Firebase only proves who someone is and
carries a copy of their role as custom claims for the web app."""

from dataclasses import dataclass
from typing import Any, Protocol

from ledger_lens.shared.config import Backend, Settings

CLOCK_SKEW_S = 10  # tolerate small clock differences between Firebase and this host


class InvalidTokenError(ValueError):
    """The ID token is missing, expired, revoked or not issued for this project."""


class AccountExistsError(ValueError):
    """An account with this email already exists."""


@dataclass(frozen=True)
class SignedIn:
    uid: str
    email: str
    name: str


class IdentityProvider(Protocol):
    def verify(self, id_token: str) -> SignedIn: ...

    def create_account(self, email: str, password: str, display_name: str) -> str:
        """Create a sign-in account and return its uid."""
        ...

    def set_claims(self, uid: str, claims: dict[str, str]) -> None: ...

    def disable(self, uid: str) -> None:
        """Block sign-in and end every session the account has."""
        ...


class FirebaseIdentity:
    """Firebase Authentication through the Admin SDK, with the service's own credentials."""

    def __init__(self, project: str) -> None:
        import firebase_admin
        from firebase_admin import auth

        self._auth: Any = auth
        try:
            self._app = firebase_admin.get_app("ledger-lens")
        except ValueError:
            self._app = firebase_admin.initialize_app(
                options={"projectId": project}, name="ledger-lens"
            )

    def verify(self, id_token: str) -> SignedIn:
        try:
            claims = self._auth.verify_id_token(
                id_token, app=self._app, clock_skew_seconds=CLOCK_SKEW_S
            )
        except Exception as exc:  # the SDK raises several types; all mean "not signed in"
            raise InvalidTokenError(type(exc).__name__) from exc
        email = claims.get("email")
        if not email:
            raise InvalidTokenError("the account has no email")
        return SignedIn(uid=claims["uid"], email=email, name=claims.get("name") or "")

    def create_account(self, email: str, password: str, display_name: str) -> str:
        try:
            user = self._auth.create_user(
                email=email, password=password, display_name=display_name or None, app=self._app
            )
        except self._auth.EmailAlreadyExistsError:
            raise AccountExistsError(email) from None
        return str(user.uid)

    def set_claims(self, uid: str, claims: dict[str, str]) -> None:
        self._auth.set_custom_user_claims(uid, claims, app=self._app)

    def disable(self, uid: str) -> None:
        self._auth.update_user(uid, disabled=True, app=self._app)
        self._auth.revoke_refresh_tokens(uid, app=self._app)


def build_identity(settings: Settings) -> IdentityProvider | None:
    """Firebase when configured; None keeps the single-lender sign-in of earlier releases."""
    if settings.identity_backend is Backend.GCP:
        if not settings.gcp_project:
            raise ValueError("LL_GCP_PROJECT is required when identity is gcp")
        return FirebaseIdentity(settings.gcp_project)
    return None
