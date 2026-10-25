"""Authenticated chat endpoint backed by the chat application use case."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from cortexstone.api.auth import AuthenticatedUser
from cortexstone.api.dependencies import (
    get_authenticated_user,
    get_chat_service,
    get_policy_principal,
)
from cortexstone.api.v1.schemas import ChatRequest, ChatResponse
from cortexstone.application.chat.schemas import ChatTurn
from cortexstone.application.chat.service import ChatService, InvalidChatModelOutput
from cortexstone.security.policy import PolicyPrincipal

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    principal: Annotated[PolicyPrincipal, Depends(get_policy_principal)],
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatResponse:
    """Resolve identity, run the application use case, and serialize its validated result."""
    if principal.principal_id != user.subject:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The authenticated principal could not be resolved.",
        )

    try:
        result = await chat_service.respond(
            principal=principal,
            turn=ChatTurn(message=payload.message, conversation_id=payload.conversation_id),
        )
    except InvalidChatModelOutput:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The model did not return a valid chat response.",
        ) from None
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="An authenticated principal is required.",
        ) from None

    return ChatResponse.model_validate(result.model_dump())
