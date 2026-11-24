"""Tests for secret redaction at shared data boundaries."""

import logging
import sys

from cortexstone.db.models.permissions import SecurityAuditEventModel
from cortexstone.security.audit.service import AuditEvent
from cortexstone.security.redaction import (
    REDACTED,
    RedactingLogFilter,
    redact_secrets,
    redact_value,
)


def test_redacts_supported_secret_patterns():
    private_key = "-----BEGIN RSA PRIVATE KEY-----\nfake-private-key\n-----END RSA PRIVATE KEY-----"
    text = (
        "api_key='fake-assignment-value' "
        "Authorization: Bearer fake.bearer.token "
        "github=ghp_abcdefghijklmnopqrstuvwxyz012345 "
        "url=postgres://alice:fake-password@db.example/test "
        f"key={private_key}"
    )

    redacted = redact_secrets(text)

    for secret in (
        "fake-assignment-value",
        "fake.bearer.token",
        "ghp_abcdefghijklmnopqrstuvwxyz012345",
        "fake-password",
        "fake-private-key",
    ):
        assert secret not in redacted
    assert redacted.count(REDACTED) >= 5


def test_recursively_redacts_structured_secret_values_and_patterns():
    data = {
        "api_key": "fake-structured-value",
        "nested": [
            {"authorization": "Bearer fake.nested.token"},
            "token=fake-inline-value",
        ],
        "ordinary": "no credentials here",
        "token_count": 12,
    }

    redacted = redact_value(data)

    assert redacted["api_key"] == REDACTED
    assert redacted["nested"][0]["authorization"] == REDACTED
    assert "fake.nested.token" not in str(redacted)
    assert "fake-inline-value" not in str(redacted)
    assert redacted["ordinary"] == "no credentials here"
    assert redacted["token_count"] == 12


def test_audit_event_redacts_text_and_nested_details():
    event = AuditEvent(
        event_type="test",
        owner_id="user_1",
        details={
            "message": "access_token=fake-audit-token",
            "credentials": {"password": "fake-audit-password"},
        },
    )

    assert "fake-audit-token" not in str(event.model_dump())
    assert "fake-audit-password" not in str(event.model_dump())

    persisted_event = SecurityAuditEventModel(
        event_type="test",
        actor_id="user_1",
        subject_id="user_1",
        details={"authorization": "Bearer fake-db-audit-token"},
    )
    assert "fake-db-audit-token" not in str(persisted_event.details)


def test_log_filter_redacts_formatted_message_and_exception_trace():
    try:
        raise RuntimeError("secret=fake-log-secret")
    except RuntimeError:
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="request failed: %s",
        args=("Bearer fake.argument.token",),
        exc_info=exc_info,
    )
    record.credentials = {"api_key": "fake-log-field"}

    assert RedactingLogFilter().filter(record)
    formatted = logging.Formatter().format(record)

    for secret in ("fake.argument.token", "fake-log-secret", "fake-log-field"):
        assert secret not in formatted
    assert REDACTED in formatted
