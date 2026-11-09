from fastapi.testclient import TestClient

from app.clients.provider import ProviderError
from app.main import create_app
from app.models import NotificationPayload
from app.request_store import RequestStore


class FakeProvider:
    def __init__(
        self,
        raw_response: str,
        notification_error: bool = False,
    ) -> None:
        self.raw_response = raw_response
        self.notification_error = notification_error
        self.extracted_inputs: list[str] = []
        self.notifications: list[NotificationPayload] = []

    async def extract(self, user_input: str) -> str:
        self.extracted_inputs.append(user_input)
        return self.raw_response

    async def notify(self, payload: NotificationPayload) -> None:
        if self.notification_error:
            raise ProviderError("notification_provider_error")
        self.notifications.append(payload)


def create_test_app(provider: FakeProvider):
    return create_app(provider_gateway=provider, request_store=RequestStore())


def test_request_lifecycle_sends_valid_extraction_once() -> None:
    provider = FakeProvider('{"to":"feda@test.com","message":"hola","type":"email"}')
    original_input = "  Manda un mail a feda@test.com diciendo hola  "

    with TestClient(create_test_app(provider)) as client:
        create_response = client.post(
            "/v1/requests",
            json={"user_input": original_input},
        )
        request_id = create_response.json()["id"]

        queued_response = client.get(f"/v1/requests/{request_id}")
        process_response = client.post(f"/v1/requests/{request_id}/process")
        sent_response = client.get(f"/v1/requests/{request_id}")
        repeated_response = client.post(f"/v1/requests/{request_id}/process")

    assert create_response.status_code == 201
    assert queued_response.json()["status"] == "queued"
    assert process_response.status_code == 200
    assert process_response.json()["status"] == "sent"
    assert sent_response.json()["status"] == "sent"
    assert repeated_response.status_code == 200
    assert provider.extracted_inputs == [original_input]
    assert [payload.model_dump() for payload in provider.notifications] == [
        {"to": "feda@test.com", "message": "hola", "type": "email"}
    ]


def test_invalid_extraction_fails_without_sending_notification() -> None:
    provider = FakeProvider('{"to":"feda@test.com","message":"hola"}')

    with TestClient(create_test_app(provider)) as client:
        request_id = client.post(
            "/v1/requests",
            json={"user_input": "Manda un mail a feda@test.com diciendo hola"},
        ).json()["id"]
        process_response = client.post(f"/v1/requests/{request_id}/process")
        status_response = client.get(f"/v1/requests/{request_id}")

    assert process_response.status_code == 200
    assert process_response.json()["status"] == "failed"
    assert status_response.json()["status"] == "failed"
    assert provider.notifications == []


def test_notification_provider_error_sets_failed_status() -> None:
    provider = FakeProvider(
        '{"to":"feda@test.com","message":"hola","type":"email"}',
        notification_error=True,
    )

    with TestClient(create_test_app(provider)) as client:
        request_id = client.post(
            "/v1/requests",
            json={"user_input": "Manda un mail a feda@test.com diciendo hola"},
        ).json()["id"]
        process_response = client.post(f"/v1/requests/{request_id}/process")

    assert process_response.status_code == 200
    assert process_response.json()["status"] == "failed"


def test_invalid_input_and_unknown_request_return_client_errors() -> None:
    provider = FakeProvider("{}")

    with TestClient(create_test_app(provider)) as client:
        empty_response = client.post("/v1/requests", json={"user_input": "   "})
        process_response = client.post("/v1/requests/unknown/process")
        status_response = client.get("/v1/requests/unknown")

    assert empty_response.status_code == 422
    assert process_response.status_code == 404
    assert status_response.status_code == 404
