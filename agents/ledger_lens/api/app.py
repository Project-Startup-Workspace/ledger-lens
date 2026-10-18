"""FastAPI application: thin HTTP layer over the coordinator.

Endpoints are synchronous on purpose: FastAPI runs them in a thread pool, and model
calls inside the agents are blocking SDK calls.
"""

import hmac
import json
import logging
import math
import threading
import time
import urllib.request
from collections.abc import Callable
from functools import lru_cache
from typing import Annotated, Any

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from ledger_lens.api.models import (
    AcknowledgeDisclosure,
    CaseSummary,
    CreateCase,
    DecisionRequest,
    ExplainRequest,
)
from ledger_lens.audit_trail.pack import PackVerification, verify_pack
from ledger_lens.auditpulse.agent import InvalidJurisdictionError
from ledger_lens.coordinator import (
    CaseNotFoundError,
    CaseStateError,
    Coordinator,
    build_services,
)
from ledger_lens.demo import demo_cases, open_demo_case
from ledger_lens.explain.agent import UnsupportedLanguageError
from ledger_lens.shared.config import Settings, get_settings
from ledger_lens.shared.llm import LlmError, LlmUnavailableError
from ledger_lens.shared.logs import configure_logging
from ledger_lens.shared.schemas import (
    ComplianceReport,
    Consent,
    CreditFile,
    EvidenceDocument,
    EvidenceKind,
    Explanation,
)
from ledger_lens.shared.storage import ConcurrentUpdateError
from ledger_lens.shared.usage import ModelBudgetExceededError

log = logging.getLogger(__name__)
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
ALLOWED_TYPES = {"image/png", "image/jpeg", "image/webp", "application/pdf", "text/csv"}
# Types browsers report for .csv files (Windows says Excel; some pickers send nothing).
CSV_ALIASES = {
    "application/vnd.ms-excel",
    "text/comma-separated-values",
    "application/octet-stream",
    "",
}
ANONYMOUS_OFFICER = "officer"
IAP_JWT_HEADER = "x-goog-iap-jwt-assertion"
IAP_KEYS_URL = "https://www.gstatic.com/iap/verify/public_key"  # PEM, by key id
IAP_ISSUER = "https://cloud.google.com/iap"
OFFICER_HEADER = "x-officer-id"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    coordinator = Coordinator(build_services(settings))
    app = FastAPI(
        title="Ledger Lens API",
        version="0.1.0",
        description="Turns informal business evidence into an auditable credit file.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    _register_errors(app)
    auth = [Depends(_bearer_auth(settings))]

    def coord() -> Coordinator:
        return coordinator

    def officer(request: Request) -> str:
        """Who is acting, from a trusted source only; never from the request body.

        1. An IAP assertion, verified against Google's keys, when the API itself sits
           behind Identity-Aware Proxy (LL_API_IAP_AUDIENCE).
        2. X-Officer-Id from the web app's server-side proxy, which holds the API token
           and has already signed the officer in.
        """
        token = request.headers.get(IAP_JWT_HEADER)
        if settings.api_iap_audience and token:
            try:
                return verify_iap_jwt(token, settings.api_iap_audience)
            except ValueError:
                raise HTTPException(401, "invalid Identity-Aware Proxy assertion") from None
        if settings.api_token and (forwarded := request.headers.get(OFFICER_HEADER)):
            return forwarded[:64]
        if settings.api_iap_audience:
            raise HTTPException(401, "Identity-Aware Proxy sign-in required")
        return ANONYMOUS_OFFICER

    Coord = Annotated[Coordinator, Depends(coord)]  # noqa: N806 - a type alias
    Officer = Annotated[str, Depends(officer)]  # noqa: N806 - a type alias

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok", "llm_provider": settings.llm_provider}

    @app.get("/jurisdictions", tags=["meta"], dependencies=auth)
    def jurisdictions(c: Coord) -> list[dict[str, str]]:
        return c.jurisdictions()

    @app.get("/demo-cases", tags=["demo"], dependencies=auth)
    def list_demo_cases() -> list[str]:
        return demo_cases()

    @app.post("/demo-cases/{slug}", tags=["demo"], dependencies=auth, status_code=201)
    def open_demo(slug: str, c: Coord, who: Officer) -> CreditFile:
        try:
            return open_demo_case(c, slug, who)
        except KeyError:
            raise HTTPException(404, f"no demo case '{slug}'") from None

    @app.post("/cases", tags=["cases"], dependencies=auth, status_code=201)
    def create_case(body: CreateCase, c: Coord, who: Officer) -> CreditFile:
        return c.create_case(
            applicant=body.applicant,
            loan=body.loan,
            consent=Consent(given=body.consent_given, method=body.consent_method),
            jurisdiction=body.jurisdiction,
            actor=who,
        )

    @app.get("/cases", tags=["cases"], dependencies=auth)
    def list_cases(c: Coord, limit: Annotated[int, Query(ge=1)] = 50) -> list[CaseSummary]:
        return [_summary(case) for case in c.list_cases(min(limit, 200))]  # capped, not refused

    @app.get("/cases/{case_id}", tags=["cases"], dependencies=auth)
    def get_case(case_id: str, c: Coord) -> CreditFile:
        return c.get(case_id)

    @app.post("/cases/{case_id}/evidence", tags=["evidence"], dependencies=auth, status_code=201)
    def upload_evidence(
        case_id: str,
        c: Coord,
        who: Officer,
        kind: Annotated[EvidenceKind, Form()],
        file: Annotated[UploadFile, File()],
    ) -> EvidenceDocument:
        content_type = (file.content_type or "").split(";")[0].strip().lower()
        if content_type in CSV_ALIASES and (file.filename or "").lower().endswith(".csv"):
            content_type = "text/csv"
        if content_type not in ALLOWED_TYPES:
            raise HTTPException(415, f"unsupported file type '{content_type}'")
        data = file.file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "file larger than 15 MB")
        if not data:
            raise HTTPException(422, "empty file")
        return c.add_evidence(
            case_id,
            kind=kind,
            filename=file.filename or "upload",
            content_type=content_type,
            data=data,
            actor=who,
        )

    @app.get("/cases/{case_id}/evidence/{evidence_id}/file", tags=["evidence"], dependencies=auth)
    def evidence_file(case_id: str, evidence_id: str, c: Coord) -> Response:
        data, content_type = c.evidence_file(case_id, evidence_id)
        return Response(data, media_type=content_type, headers={"Cache-Control": "private"})

    @app.post("/cases/{case_id}/assess", tags=["assessment"], dependencies=auth)
    def assess(case_id: str, c: Coord, who: Officer) -> CreditFile:
        return c.assess(case_id, who)

    @app.get("/cases/{case_id}/compliance", tags=["assessment"], dependencies=auth)
    def compliance(case_id: str, jurisdiction: str, c: Coord) -> ComplianceReport:
        return c.compliance_view(case_id, jurisdiction)

    @app.post("/cases/{case_id}/explanation", tags=["assessment"], dependencies=auth)
    def explain(case_id: str, body: ExplainRequest, c: Coord, who: Officer) -> Explanation:
        return c.explain_in(case_id, body.language, who)

    @app.get("/cases/{case_id}/report", tags=["assessment"], dependencies=auth)
    def report(case_id: str, c: Coord) -> Response:
        return Response(c.officer_report(case_id), media_type="text/markdown; charset=utf-8")

    @app.get("/cases/{case_id}/explanation/audio", tags=["assessment"], dependencies=auth)
    def explanation_audio(case_id: str, c: Coord) -> Response:
        return Response(c.speech(case_id), media_type="audio/wav")

    @app.post("/cases/{case_id}/disclosure/acknowledge", tags=["decision"], dependencies=auth)
    def acknowledge(
        case_id: str, body: AcknowledgeDisclosure, c: Coord, who: Officer
    ) -> CreditFile:
        return c.acknowledge_disclosure(case_id, blank_fields=body.blank_fields, actor=who)

    @app.post("/cases/{case_id}/decision", tags=["decision"], dependencies=auth)
    def decide(case_id: str, body: DecisionRequest, c: Coord, who: Officer) -> CreditFile:
        return c.decide(case_id, officer_id=who, outcome=body.outcome, reason=body.reason)

    @app.get("/cases/{case_id}/audit", tags=["audit"], dependencies=auth)
    def audit_events(case_id: str, c: Coord) -> dict[str, Any]:
        events, verification = c.audit_log(case_id)
        return {
            "verification": verification.model_dump(),
            "events": [e.model_dump(mode="json") for e in events],
        }

    # POST: every export is recorded in the audit chain and stored under retention, so a
    # prefetch, link preview or retry must never create one.
    @app.post("/cases/{case_id}/audit-pack", tags=["audit"], dependencies=auth)
    def audit_pack(case_id: str, c: Coord, who: Officer) -> Response:
        pack = c.export_audit_pack(case_id, who)
        headers = {"Content-Disposition": f'attachment; filename="audit-pack-{case_id}.zip"'}
        return Response(pack, media_type="application/zip", headers=headers)

    @app.post("/audit-packs/verify", tags=["audit"], dependencies=auth)
    def verify_uploaded_pack(c: Coord, file: Annotated[UploadFile, File()]) -> PackVerification:
        return verify_pack(file.file.read(MAX_UPLOAD_BYTES), c.signing_public_key())

    @app.get("/audit-packs/public-key", tags=["audit"])
    def public_key(c: Coord) -> Response:
        return Response(c.signing_public_key(), media_type="application/x-pem-file")

    return app


class _IapKeys:
    """IAP's public keys (PEM, by key id): cached for an hour, refetched early when a
    token names a key id not yet seen (Google rotates keys), and never fetched while
    holding the lock, so a slow or failing fetch cannot queue every request behind it.
    """

    TTL_S = 3600.0
    RETRY_AFTER_FAILURE_S = 30.0

    def __init__(self) -> None:
        self._keys: dict[str, str] = {}
        self._fetched_at = -math.inf
        self._failed_at = -math.inf
        self._lock = threading.Lock()

    def get(self, key_id: str | None) -> dict[str, str]:
        now = time.monotonic()
        with self._lock:
            fresh = now - self._fetched_at <= self.TTL_S
            if fresh and (key_id is None or key_id in self._keys):
                return self._keys
            if now - self._failed_at < self.RETRY_AFTER_FAILURE_S:
                raise ValueError("IAP keys unavailable; retrying shortly")
        try:
            keys = fetch_iap_keys()
        except Exception as exc:
            with self._lock:
                self._failed_at = time.monotonic()
            raise ValueError("IAP keys could not be fetched") from exc
        with self._lock:
            self._keys, self._fetched_at = keys, time.monotonic()
            return self._keys


def fetch_iap_keys() -> dict[str, str]:
    with urllib.request.urlopen(IAP_KEYS_URL, timeout=10) as response:
        keys = json.loads(response.read())
    if not isinstance(keys, dict):
        raise ValueError("unexpected IAP key format")
    return {str(k): str(v) for k, v in keys.items()}


_iap_keys = _IapKeys()
IAP_CLOCK_SKEW_S = 30  # tolerate small clock differences between IAP and this host


def verify_iap_jwt(token: str, audience: str) -> str:
    """The signed-in email from an IAP assertion; ValueError if it is not genuine.

    Any failure (bad signature, wrong audience or issuer, expiry, malformed token, keys
    unreachable, verification library missing) is reported as ValueError, so callers
    answer 401, never 500.
    """
    try:
        import google.auth.jwt

        header = google.auth.jwt.decode_header(token)  # type: ignore[no-untyped-call]
        key_id = header.get("kid") if isinstance(header, dict) else None
        claims = google.auth.jwt.decode(  # type: ignore[no-untyped-call]
            token,
            certs=_iap_keys.get(key_id),
            audience=audience,
            clock_skew_in_seconds=IAP_CLOCK_SKEW_S,
        )
    except ImportError as exc:
        log.error("LL_API_IAP_AUDIENCE is set but google-auth is not installed (gcp extra)")
        raise ValueError("IAP verification unavailable") from exc
    except ValueError:
        raise
    except Exception as exc:  # the library raises several types; all mean "not genuine"
        raise ValueError(f"IAP assertion rejected: {type(exc).__name__}") from exc
    if claims.get("iss") != IAP_ISSUER or not claims.get("email"):
        raise ValueError("not an Identity-Aware Proxy assertion")
    return str(claims["email"])


def _bearer_auth(settings: Settings) -> Callable[..., None]:
    """Require `Authorization: Bearer <LL_API_TOKEN>` when a token is configured."""

    def check(authorization: Annotated[str | None, Header()] = None) -> None:
        # Stripped: secrets created with `echo` or `openssl` often end in a newline.
        expected = settings.api_token.get_secret_value().strip() if settings.api_token else None
        if expected is None:
            return
        supplied = (authorization or "").removeprefix("Bearer ").strip()
        if not hmac.compare_digest(supplied.encode(), expected.encode()):
            raise HTTPException(401, "missing or invalid API token")

    return check


def _register_errors(app: FastAPI) -> None:
    statuses: dict[type[Exception], int] = {
        CaseNotFoundError: 404,
        CaseStateError: 409,
        ConcurrentUpdateError: 409,
        UnsupportedLanguageError: 422,
        InvalidJurisdictionError: 422,
        ModelBudgetExceededError: 429,  # matched before its parent LlmUnavailableError
        LlmUnavailableError: 503,
        LlmError: 502,
    }
    for error, status in statuses.items():

        def handler(_: Request, exc: Exception, status: int = status) -> JSONResponse:
            return JSONResponse({"detail": str(exc) or type(exc).__name__}, status_code=status)

        app.add_exception_handler(error, handler)


def _summary(case: CreditFile) -> CaseSummary:
    return CaseSummary(
        case_id=case.case_id,
        status=case.status,
        business_name=case.applicant.business_name,
        jurisdiction=case.jurisdiction,
        amount=float(case.loan.amount),
        currency=case.loan.currency,
        grade=case.risk.grade if case.risk else None,
        recommendation=case.risk.recommendation if case.risk else None,
        created_at=case.created_at.isoformat(),
    )


@lru_cache
def _default_app() -> FastAPI:
    return create_app()


def __getattr__(name: str) -> FastAPI:
    """`uvicorn ledger_lens.api.app:app` builds the app on first access, not at import."""
    if name == "app":
        return _default_app()
    raise AttributeError(name)
