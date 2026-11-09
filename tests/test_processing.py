import asyncio
from threading import Event

from app.models import NotificationPayload, RequestStatus
from app.processing import ProcessingService
from app.request_store import RequestStore


class BlockingProvider:
    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()
        self.extracted_inputs: list[str] = []
        self.notifications: list[NotificationPayload] = []

    async def extract(self, user_input: str) -> str:
        self.extracted_inputs.append(user_input)
        self.started.set()
        await asyncio.to_thread(self.release.wait)
        return '{"to":"feda@test.com","message":"hello","type":"email"}'

    async def notify(self, payload: NotificationPayload) -> None:
        self.notifications.append(payload)


def test_concurrent_processing_calls_send_only_once() -> None:
    store = RequestStore()
    provider = BlockingProvider()
    service = ProcessingService(store, provider)
    original_input = "Send an email to feda@test.com"
    record = store.create(original_input)

    async def run_processing() -> None:
        first_task = asyncio.create_task(service.process_request(record.id))
        try:
            started = await asyncio.to_thread(provider.started.wait, 2)
            assert started

            duplicate_result = await service.process_request(record.id)
            assert duplicate_result is not None
            assert duplicate_result.status == RequestStatus.PROCESSING
        finally:
            provider.release.set()

        first_result = await first_task
        assert first_result is not None
        assert first_result.status == RequestStatus.SENT

    asyncio.run(run_processing())

    assert provider.extracted_inputs == [original_input]
    assert len(provider.notifications) == 1
