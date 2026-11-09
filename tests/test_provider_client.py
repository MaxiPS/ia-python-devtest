import json

import httpx
from fastapi.testclient import TestClient

from app.main import create_app
from app.request_store import RequestStore
from app.settings import Settings


def test_provider_requests_use_expected_auth_and_payloads() -> None:
    requests: list[tuple[str, str, str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_body = json.loads(request.content)
        requests.append(
            (
                request.method,
                request.url.path,
                request.headers.get("X-API-Key", ""),
                request_body,
            )
        )
        if request.url.path == "/v1/ai/extract":
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    '{"to":"feda@test.com",'
                                    '"message":"hola","type":"email"}'
                                )
                            }
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={"status": "delivered", "provider_id": "p-test"},
        )

    application = create_app(
        request_store=RequestStore(),
        settings=Settings(
            provider_base_url="http://provider.test",
            provider_api_key="test-api-key",
        ),
        http_transport=httpx.MockTransport(handler),
    )

    with TestClient(application) as client:
        request_id = client.post(
            "/v1/requests",
            json={"user_input": "Manda un mail a feda@test.com diciendo hola"},
        ).json()["id"]
        process_response = client.post(f"/v1/requests/{request_id}/process")

    assert process_response.status_code == 200
    assert process_response.json()["status"] == "sent"
    assert [(method, path, api_key) for method, path, api_key, _ in requests] == [
        ("POST", "/v1/ai/extract", "test-api-key"),
        ("POST", "/v1/notify", "test-api-key"),
    ]
    assert requests[0][3]["messages"][1] == {
        "role": "user",
        "content": "Manda un mail a feda@test.com diciendo hola",
    }
    assert requests[0][3]["messages"][0]["role"] == "system"
    assert requests[1][3] == {
        "to": "feda@test.com",
        "message": "hola",
        "type": "email",
    }
