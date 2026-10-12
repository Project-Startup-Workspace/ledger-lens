"""Clause excerpts for citations.

Locally the excerpt is the clause summary held in the rule pack. With Vertex AI RAG
Engine, the passage that best matches the clause is retrieved from the indexed
regulator documents, so the officer sees the regulator's own words.
"""

import logging
from typing import Any, Protocol

from ledger_lens.auditpulse.packs import Clause, Source
from ledger_lens.shared.config import Backend, Settings

log = logging.getLogger(__name__)


class ClauseRetriever(Protocol):
    def excerpt(self, source: Source, clause: Clause) -> str: ...


class PackSummaryRetriever:
    def excerpt(self, source: Source, clause: Clause) -> str:
        return clause.summary


class VertexRagRetriever:
    """Queries a RAG Engine corpus through the REST API; falls back to the pack summary."""

    def __init__(self, settings: Settings) -> None:
        import google.auth
        from google.auth.transport.requests import AuthorizedSession

        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        self._session = AuthorizedSession(credentials)  # type: ignore[no-untyped-call]
        region = settings.gcp_region
        self._url = (
            f"https://{region}-aiplatform.googleapis.com/v1/projects/{settings.gcp_project}"
            f"/locations/{region}:retrieveContexts"
        )
        self._corpus = settings.rag_corpus
        self._timeout = settings.llm_timeout_s

    def excerpt(self, source: Source, clause: Clause) -> str:
        body: dict[str, Any] = {
            "vertex_rag_store": {"rag_resources": [{"rag_corpus": self._corpus}]},
            "query": {
                "text": f"{source.title}: {clause.summary}",
                "rag_retrieval_config": {"top_k": 1},
            },
        }
        try:
            response = self._session.post(self._url, json=body, timeout=self._timeout)
            response.raise_for_status()
            contexts = response.json().get("contexts", {}).get("contexts", [])
        except Exception:  # retrieval improves a citation; it must never block a check
            log.warning("rag retrieval failed; using pack summary", exc_info=True)
            return clause.summary
        return str(contexts[0]["text"]).strip() if contexts else clause.summary


def build_retriever(settings: Settings) -> ClauseRetriever:
    if settings.retrieval_backend is Backend.GCP and settings.rag_corpus:
        return VertexRagRetriever(settings)
    return PackSummaryRetriever()
