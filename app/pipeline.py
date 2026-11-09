import ast
import json
import re
from collections.abc import Iterator
from typing import Any

from pydantic import ValidationError

from app.models import NotificationPayload

MAX_RESPONSE_LENGTH = 32_000

FIELD_ALIASES = {
    "to": "to",
    "recipient": "to",
    "destination": "to",
    "message": "message",
    "body": "message",
    "text": "message",
    "type": "type",
    "channel": "type",
    "method": "type",
}
IGNORED_FIELDS = frozenset({"confidence", "latency_ms"})
REPAIRABLE_KEYS = frozenset(FIELD_ALIASES) | IGNORED_FIELDS
REFUSAL_PREFIXES = (
    "lo siento, como ia no tengo permitido procesar datos de contacto personales",
    "error: el contenido del mensaje viola las políticas de seguridad",
    "refused: content analysis flagged sensitive information",
)
EMAIL_PATTERN = re.compile(r"[\w.-]+@[\w.-]+\.\w+")
PHONE_PATTERN = re.compile(r"\d{3}-?\d{3}-?\d{3,4}")


class ExtractionError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _DuplicateKeyError(ValueError):
    pass


def extract_notification(raw_response: str, original_input: str) -> NotificationPayload:
    if not raw_response or not raw_response.strip():
        raise ExtractionError("empty_ai_response")
    if len(raw_response) > MAX_RESPONSE_LENGTH:
        raise ExtractionError("ai_response_too_large")

    normalized_response = raw_response.strip().casefold()
    if normalized_response.startswith(REFUSAL_PREFIXES):
        raise ExtractionError("ai_refusal")

    parsed = _parse_first_object(raw_response)
    normalized = _normalize_fields(parsed)

    try:
        payload = NotificationPayload.model_validate(normalized)
    except ValidationError as error:
        raise ExtractionError("invalid_notification_fields") from error

    _validate_destination(payload, original_input)
    return payload


def _parse_first_object(raw_response: str) -> dict[str, Any]:
    for candidate in _balanced_objects(raw_response):
        parsed = _parse_candidate(candidate)
        if parsed is not None:
            return parsed
    raise ExtractionError("invalid_ai_json")


def _balanced_objects(text: str) -> Iterator[str]:
    for start, character in enumerate(text):
        if character != "{":
            continue

        depth = 0
        quote: str | None = None
        escaped = False
        for index in range(start, len(text)):
            current = text[index]
            if quote is not None:
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == quote:
                    quote = None
                continue

            if current in ('"', "'"):
                quote = current
            elif current == "{":
                depth += 1
            elif current == "}":
                depth -= 1
                if depth == 0:
                    yield text[start : index + 1]
                    break


def _parse_candidate(candidate: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(candidate, object_pairs_hook=_unique_object)
        if isinstance(parsed, dict):
            return parsed
    except _DuplicateKeyError as error:
        raise ExtractionError("duplicate_json_key") from error
    except (json.JSONDecodeError, ValueError):
        pass

    try:
        parsed = ast.literal_eval(candidate)
        if isinstance(parsed, dict):
            return parsed
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        pass

    repaired = _quote_unquoted_keys(candidate)
    if repaired is None:
        return None

    try:
        parsed = json.loads(repaired, object_pairs_hook=_unique_object)
    except _DuplicateKeyError as error:
        raise ExtractionError("duplicate_json_key") from error
    except (json.JSONDecodeError, ValueError):
        return None

    return parsed if isinstance(parsed, dict) else None


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError("duplicate object key")
        result[key] = value
    return result


def _quote_unquoted_keys(candidate: str) -> str | None:
    output: list[str] = []
    index = 0
    depth = 0
    quote: str | None = None
    escaped = False
    expecting_key = False
    changed = False

    while index < len(candidate):
        character = candidate[index]

        if quote is not None:
            output.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            index += 1
            continue

        if character in ('"', "'"):
            if depth == 1 and expecting_key:
                expecting_key = False
            quote = character
            output.append(character)
        elif character == "{":
            depth += 1
            output.append(character)
            if depth == 1:
                expecting_key = True
        elif character == "}":
            depth -= 1
            output.append(character)
        elif depth == 1 and expecting_key and character.isspace():
            output.append(character)
        elif depth == 1 and expecting_key:
            match = re.match(r"[A-Za-z_][A-Za-z0-9_]*", candidate[index:])
            if match is None:
                output.append(character)
                expecting_key = False
            else:
                key = match.group(0)
                end = index + len(key)
                while end < len(candidate) and candidate[end].isspace():
                    end += 1
                if (
                    key.casefold() in REPAIRABLE_KEYS
                    and end < len(candidate)
                    and candidate[end] == ":"
                ):
                    output.append(json.dumps(key))
                    index += len(key) - 1
                    expecting_key = False
                    changed = True
                else:
                    output.append(character)
                    expecting_key = False
        else:
            output.append(character)
            if depth == 1 and character == ",":
                expecting_key = True

        index += 1

    return "".join(output) if changed else None


def _normalize_fields(parsed: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in parsed.items():
        if not isinstance(key, str):
            raise ExtractionError("invalid_ai_key")

        canonical_key = FIELD_ALIASES.get(key.casefold())
        if canonical_key is None:
            continue

        if canonical_key in normalized and normalized[canonical_key] != value:
            raise ExtractionError("conflicting_ai_fields")
        normalized[canonical_key] = value

    for key in ("to", "message"):
        value = normalized.get(key)
        if isinstance(value, str):
            normalized[key] = value.strip()

    notification_type = normalized.get("type")
    if isinstance(notification_type, str):
        normalized["type"] = notification_type.strip().casefold()

    return normalized


def _validate_destination(payload: NotificationPayload, original_input: str) -> None:
    if payload.type == "email":
        if EMAIL_PATTERN.fullmatch(payload.to) is None:
            raise ExtractionError("invalid_email_destination")
    elif PHONE_PATTERN.fullmatch(payload.to) is None:
        raise ExtractionError("invalid_sms_destination")

    original_destinations = _find_original_destinations(original_input)
    if len(original_destinations) > 1:
        raise ExtractionError("ambiguous_original_destination")
    if not original_destinations:
        return

    original_type, original_destination = original_destinations[0]
    if original_type != payload.type:
        raise ExtractionError("notification_type_mismatch")

    if original_type == "email":
        matches = original_destination.casefold() == payload.to.casefold()
    else:
        matches = _digits_only(original_destination) == _digits_only(payload.to)

    if not matches:
        raise ExtractionError("destination_mismatch")


def _find_original_destinations(text: str) -> list[tuple[str, str]]:
    matches: list[tuple[str, str, int, int]] = []
    email_spans: list[tuple[int, int]] = []

    for match in EMAIL_PATTERN.finditer(text):
        email_spans.append(match.span())
        matches.append(("email", match.group(0), *match.span()))

    for match in PHONE_PATTERN.finditer(text):
        overlaps_email = any(
            match.start() < email_end and match.end() > email_start
            for email_start, email_end in email_spans
        )
        if not overlaps_email:
            matches.append(("sms", match.group(0), *match.span()))

    unique: dict[tuple[str, str], str] = {}
    for destination_type, value, _, _ in matches:
        normalized_value = (
            value.casefold() if destination_type == "email" else _digits_only(value)
        )
        unique[(destination_type, normalized_value)] = value

    return [
        (destination_type, value) for (destination_type, _), value in unique.items()
    ]


def _digits_only(value: str) -> str:
    return "".join(character for character in value if character.isdigit())
