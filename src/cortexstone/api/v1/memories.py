"""Owner-scoped memory endpoints defined by the frontend API contract."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from cortexstone.api.auth import AuthenticatedUser
from cortexstone.api.dependencies import (
    get_authenticated_user,
    get_db_session,
    get_memory_service,
)
from cortexstone.api.v1.schemas import MemoryCreateRequest, MemoryPageResponse, MemoryResponse
from cortexstone.application.memory.service import MemoryService
from cortexstone.memory.schemas import MemoryFilter

router = APIRouter(prefix="/memories", tags=["memories"])


@router.post("", response_model=MemoryResponse, status_code=status.HTTP_201_CREATED)
async def create_memory(
    payload: MemoryCreateRequest,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    memory_service: Annotated[MemoryService, Depends(get_memory_service)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MemoryResponse:
    """Create a memory owned by the authenticated token subject."""
    memory = await memory_service.create_memory(
        owner_id=user.subject,
        item=payload.to_domain(),
    )
    await session.commit()
    return MemoryResponse.from_memory(memory)


@router.get("", response_model=MemoryPageResponse)
async def list_memories(
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    memory_service: Annotated[MemoryService, Depends(get_memory_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MemoryPageResponse:
    """List the authenticated user's active memories in a page envelope."""
    filters = MemoryFilter(
        include_deleted=False,
        limit=limit,
        offset=offset,
    )
    memories = await memory_service.list_memories(owner_id=user.subject, filter_params=filters)
    total = await memory_service.count_memories(owner_id=user.subject, filter_params=filters)
    return MemoryPageResponse(
        items=[MemoryResponse.from_memory(memory) for memory in memories],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{memory_id}", response_model=MemoryResponse)
async def get_memory(
    memory_id: str,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    memory_service: Annotated[MemoryService, Depends(get_memory_service)],
) -> MemoryResponse:
    """Read an active memory without disclosing cross-owner existence."""
    try:
        memory_uuid = UUID(memory_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found."
        ) from None

    memory = await memory_service.get_memory(owner_id=user.subject, memory_id=memory_uuid)
    if memory is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found.")
    return MemoryResponse.from_memory(memory)


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def forget_memory(
    memory_id: str,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    memory_service: Annotated[MemoryService, Depends(get_memory_service)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Response:
    """Forget an owner's memory and return the contract's empty success response."""
    try:
        memory_uuid = UUID(memory_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found."
        ) from None

    receipt = await memory_service.forget_memory(owner_id=user.subject, memory_id=memory_uuid)
    if receipt.status == "not_found":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found.")
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
