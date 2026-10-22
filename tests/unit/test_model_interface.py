"""Unit tests for provider-neutral model message and response types."""

from cortexstone.agent.models.interface import (
    ModelMessage,
    ModelResponse,
    Role,
    UsageMetadata,
)


def test_model_message_serializes_role_and_content():
    message = ModelMessage(role=Role.USER, content="Hello")

    assert message.to_dict() == {"role": "user", "content": "Hello"}


def test_model_message_serializes_each_supported_role():
    for role in Role:
        message = ModelMessage(role=role, content="Test content")

        assert message.to_dict()["role"] == role.value


def test_model_message_includes_non_empty_name():
    message = ModelMessage(role=Role.TOOL, content="result", name="notes.search")

    assert message.to_dict() == {
        "role": "tool",
        "content": "result",
        "name": "notes.search",
    }


def test_model_message_excludes_missing_name():
    message = ModelMessage(role=Role.USER, content="Hello", name=None)

    assert "name" not in message.to_dict()


def test_usage_metadata_defaults_to_zero():
    usage = UsageMetadata()

    assert usage.prompt_tokens == 0
    assert usage.completion_tokens == 0
    assert usage.total_tokens == 0
    assert usage.latency_ms == 0.0


def test_model_response_preserves_text_and_metadata():
    usage = UsageMetadata(
        prompt_tokens=3,
        completion_tokens=2,
        total_tokens=5,
        latency_ms=12.5,
    )

    response = ModelResponse(
        raw_content="Hello",
        model_id="test-model",
        finish_reason="stop",
        usage=usage,
    )

    assert response.raw_content == "Hello"
    assert response.parsed is None
    assert response.model_id == "test-model"
    assert response.finish_reason == "stop"
    assert response.usage is usage
