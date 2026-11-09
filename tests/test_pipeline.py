import pytest

from app.pipeline import ExtractionError, extract_notification

ORIGINAL_INPUT = "Manda un mail a feda@test.com diciendo hola"
EXPECTED_NOTIFICATION = {
    "to": "feda@test.com",
    "message": "Hola desde el test",
    "type": "email",
}


@pytest.mark.parametrize(
    "raw_response",
    [
        '{"to":"feda@test.com","message":"Hola desde el test","type":"email"}',
        'Respuesta extraída:\n```json\n{"to":"feda@test.com","message":"Hola desde el test","type":"email"}\n```',
        'Output: {"Recipient":"feda@test.com","body":"Hola desde el test","channel":"EMAIL","confidence":0.99}',
        "{'to': 'feda@test.com', 'message': 'Hola desde el test', 'type': 'email'}",
        '{to: "feda@test.com", message: "Hola desde el test", type: "email"}',
    ],
)
def test_extract_notification_accepts_supported_response_formats(
    raw_response: str,
) -> None:
    notification = extract_notification(raw_response, ORIGINAL_INPUT)

    assert notification.model_dump() == EXPECTED_NOTIFICATION


@pytest.mark.parametrize(
    ("raw_response", "original_input", "error_code"),
    [
        (
            "Refused: Content analysis flagged sensitive information.",
            ORIGINAL_INPUT,
            "ai_refusal",
        ),
        (
            '{"to":"feda@test.com","message":"Hola"}',
            ORIGINAL_INPUT,
            "invalid_notification_fields",
        ),
        (
            '{"to":"feda@test.com","message":"Hola","type":"email" ...',
            ORIGINAL_INPUT,
            "invalid_ai_json",
        ),
        (
            '{"to":"other@test.com","message":"Hola","type":"email"}',
            ORIGINAL_INPUT,
            "destination_mismatch",
        ),
        (
            '{"to":"feda@test.com","Recipient":"other@test.com","message":"Hola","type":"email"}',
            ORIGINAL_INPUT,
            "conflicting_ai_fields",
        ),
        (
            '{"to":"feda@test.com","message":"Hola","type":"push"}',
            ORIGINAL_INPUT,
            "invalid_notification_fields",
        ),
    ],
)
def test_extract_notification_rejects_untrusted_responses(
    raw_response: str,
    original_input: str,
    error_code: str,
) -> None:
    with pytest.raises(ExtractionError) as error:
        extract_notification(raw_response, original_input)

    assert error.value.code == error_code
