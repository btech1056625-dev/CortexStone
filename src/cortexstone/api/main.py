"""FastAPI application entry point."""

import logging
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from cortexstone.api.v1.router import operational_router
from cortexstone.api.v1.router import router as v1_router

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Cortexstone API",
    description="Cortexstone backend API.",
    version="0.1.0",
    openapi_url="/api/v1/openapi.json",
    docs_url="/api/v1/docs",
    redoc_url=None,
)


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = uuid4().hex
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


app.include_router(operational_router)
app.include_router(v1_router, prefix="/api/v1")


def _error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    return JSONResponse(
        status_code=status_code,
        headers={"X-Request-ID": request_id} if request_id else None,
        content={
            "error": {"code": code, "message": message},
            "request_id": request_id,
        },
    )


@app.exception_handler(StarletteHTTPException)
async def handle_http_error(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    code_by_status = {
        404: "not_found",
        422: "invalid_request",
        503: "service_unavailable",
    }
    code = code_by_status.get(exc.status_code, "http_error")
    message = exc.detail if isinstance(exc.detail, str) else "The request could not be completed."
    return _error_response(request, exc.status_code, code, message)


@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    return _error_response(
        request,
        422,
        "invalid_request",
        "Request validation failed.",
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "Unhandled request error (%s)",
        type(exc).__name__,
        extra={"request_id": getattr(request.state, "request_id", None)},
    )
    return _error_response(
        request,
        500,
        "internal_server_error",
        "An unexpected error occurred.",
    )
