import logging

from app.clients.provider import ProviderError, ProviderGateway
from app.models import RequestStatus
from app.pipeline import ExtractionError, extract_notification
from app.request_store import RequestRecord, RequestStore

logger = logging.getLogger(__name__)


class ProcessingService:
    def __init__(self, request_store: RequestStore, provider: ProviderGateway) -> None:
        self._request_store = request_store
        self._provider = provider

    async def process_request(self, request_id: str) -> RequestRecord | None:
        record, claimed = self._request_store.claim_for_processing(request_id)
        if record is None or not claimed:
            return record

        try:
            raw_response = await self._provider.extract(record.user_input)
            notification = extract_notification(raw_response, record.user_input)
            await self._provider.notify(notification)
        except ExtractionError as error:
            return self._request_store.complete(
                request_id,
                RequestStatus.FAILED,
                failure_code=error.code,
            )
        except ProviderError as error:
            return self._request_store.complete(
                request_id,
                RequestStatus.FAILED,
                failure_code=error.code,
            )
        except Exception:  # noqa: BLE001 - accepted requests must leave processing on failure.
            logger.error("Unexpected processing failure for request_id=%s", request_id)
            return self._request_store.complete(
                request_id,
                RequestStatus.FAILED,
                failure_code="internal_error",
            )

        return self._request_store.complete(request_id, RequestStatus.SENT)
