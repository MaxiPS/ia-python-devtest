from dataclasses import dataclass, replace
from threading import Lock
from uuid import uuid4

from app.models import RequestStatus


@dataclass(frozen=True, slots=True)
class RequestRecord:
    id: str
    user_input: str
    status: RequestStatus
    failure_code: str | None = None


class RequestStore:
    def __init__(self) -> None:
        self._records: dict[str, RequestRecord] = {}
        self._lock = Lock()

    def create(self, user_input: str) -> RequestRecord:
        record = RequestRecord(
            id=str(uuid4()),
            user_input=user_input,
            status=RequestStatus.QUEUED,
        )
        with self._lock:
            self._records[record.id] = record
        return record

    def get(self, request_id: str) -> RequestRecord | None:
        with self._lock:
            return self._records.get(request_id)

    def claim_for_processing(
        self, request_id: str
    ) -> tuple[RequestRecord | None, bool]:
        with self._lock:
            record = self._records.get(request_id)
            if record is None:
                return None, False

            if record.status != RequestStatus.QUEUED:
                return record, False

            processing_record = replace(record, status=RequestStatus.PROCESSING)
            self._records[request_id] = processing_record
            return processing_record, True

    def complete(
        self,
        request_id: str,
        final_status: RequestStatus,
        failure_code: str | None = None,
    ) -> RequestRecord:
        if final_status not in (RequestStatus.SENT, RequestStatus.FAILED):
            raise ValueError("final_status must be sent or failed")

        with self._lock:
            record = self._records.get(request_id)
            if record is None or record.status != RequestStatus.PROCESSING:
                raise ValueError("request is not processing")

            completed_record = replace(
                record,
                status=final_status,
                failure_code=failure_code,
            )
            self._records[request_id] = completed_record
            return completed_record
