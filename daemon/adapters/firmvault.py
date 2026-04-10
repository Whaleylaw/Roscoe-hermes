"""FirmVault adapter — interface only.

FirmVault is the secure document/evidence store for the paralegal stack.
Workers read source documents from FirmVault and write results back to it.

TODO: Implement once the FirmVault API is defined.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from daemon.adapters.base import HealthCheckable, HealthStatus

logger = logging.getLogger("daemon.adapters.firmvault")


class FirmVaultAdapter(HealthCheckable):
    """Stub adapter for FirmVault.

    All methods return safe no-op values.  Replace the bodies with real
    HTTP calls once the FirmVault API is available.
    """

    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/") if base_url else ""
        self._timeout = timeout
        if not self._base_url:
            logger.info("FirmVault URL not configured — adapter disabled")

    @property
    def configured(self) -> bool:
        return bool(self._base_url)

    # ── Health ────────────────────────────────────────────────────────

    async def health_check(self) -> HealthStatus:
        if not self.configured:
            return HealthStatus(
                service_name="firmvault",
                healthy=False,
                error="URL not configured",
            )
        # TODO: GET {self._base_url}/health
        return HealthStatus(
            service_name="firmvault",
            healthy=False,
            error="Not implemented",
        )

    # ── Document operations ───────────────────────────────────────────

    async def fetch_document(self, document_id: str) -> Optional[dict]:
        """Retrieve a document/evidence item from FirmVault.

        TODO: GET {self._base_url}/api/documents/{document_id}
        """
        if not self.configured:
            return None
        logger.debug("fetch_document(%s): stub — not yet implemented", document_id)
        return None

    async def store_result(self, task_id: str, data: Any) -> bool:
        """Write a worker result back to FirmVault.

        TODO: POST {self._base_url}/api/documents
              body: {"task_id": task_id, "data": data, "source": "hermes-worker"}
        """
        if not self.configured:
            return False
        logger.debug("store_result(%s): stub — not yet implemented", task_id)
        return False
