import pytest
from pydantic import ValidationError

from cortexstone.api.v1.schemas import ChatRequest, ChatResponse


def test_chat_request_strips_message_whitespace():
    request = ChatRequest.model_validate({"message": "  Remember this  "})

    assert request.message == "Remember this"
    assert request.conversation_id is None


@pytest.mark.parametrize(
    "payload",
    [
        {"message": ""},
        {"message": "   "},
        {"message": "x" * 10_001},
        {"message": "hello", "unexpected": True},
        {"message": "hello", "conversation_id": "invalid/id"},
    ],
)
def test_chat_request_rejects_invalid_payloads(payload):
    with pytest.raises(ValidationError):
        ChatRequest.model_validate(payload)


def test_chat_response_accepts_answer():
    response = ChatResponse.model_validate({"conversation_id": "conversation_1", "answer": "Hello"})

    assert response.conversation_id == "conversation_1"
    assert response.answer == "Hello"
    assert response.proposed_actions == []


def test_chat_response_requires_answer_or_action():
    with pytest.raises(ValidationError):
        ChatResponse.model_validate({})


def test_chat_response_accepts_typed_action_proposals():
    response = ChatResponse.model_validate(
        {
            "proposed_actions": [
                {
                    "tool_name": "notes.search",
                    "target_ref": "personal",
                    "purpose": "Find the requested note",
                }
            ]
        }
    )

    assert response.answer is None
    assert response.proposed_actions[0].tool_name == "notes.search"


def test_chat_response_rejects_invalid_nested_action():
    with pytest.raises(ValidationError):
        ChatResponse.model_validate(
            {
                "proposed_actions": [
                    {
                        "tool_name": " ",
                        "target_ref": "personal",
                        "purpose": "Find the requested note",
                    }
                ]
            }
        )


def test_chat_response_rejects_model_authorization_fields():
    with pytest.raises(ValidationError):
        ChatResponse.model_validate(
            {
                "proposed_actions": [
                    {
                        "tool_name": "notes.search",
                        "target_ref": "personal",
                        "purpose": "Find the requested note",
                        "is_authorized": True,
                    }
                ]
            }
        )


def test_chat_response_limits_action_proposals():
    with pytest.raises(ValidationError):
        ChatResponse.model_validate(
            {
                "proposed_actions": [
                    {
                        "tool_name": "notes.search",
                        "target_ref": "personal",
                        "purpose": "Find the requested note",
                    }
                    for _ in range(4)
                ],
            }
        )
