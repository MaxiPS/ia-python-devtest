from concurrent.futures import ThreadPoolExecutor

from app.models import RequestStatus
from app.request_store import RequestStore


def test_only_one_concurrent_call_can_claim_a_request() -> None:
    store = RequestStore()
    record = store.create("Send an email to feda@test.com")

    with ThreadPoolExecutor(max_workers=16) as executor:
        claims = list(
            executor.map(
                lambda _: store.claim_for_processing(record.id),
                range(32),
            )
        )

    claimed_records = [item for item, claimed in claims if claimed]

    assert len(claimed_records) == 1
    assert all(item is not None for item, _ in claims)
    assert all(item.status == RequestStatus.PROCESSING for item, _ in claims if item)
