from fastapi import Request, status
from fastapi.responses import JSONResponse

from app.application.exceptions import (
    ApplicationError,
    EntityNotFoundError,
    ProviderUnavailableError,
)
from app.domain.exceptions import DomainError


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, EntityNotFoundError):
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": "NOT_FOUND", "message": str(exc)},
        )

    if isinstance(exc, ProviderUnavailableError):
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            headers={"Retry-After": "300"},
            content={"error": "PROVIDER_UNAVAILABLE", "message": str(exc)},
        )

    if isinstance(exc, (DomainError, ApplicationError)):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "BUSINESS_RULE_VIOLATION", "message": str(exc)},
        )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "INTERNAL_SERVER_ERROR", "message": "An unexpected error occurred"},
    )
