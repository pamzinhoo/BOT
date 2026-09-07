from __future__ import annotations

from fastapi import HTTPException, Request, status

_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


async def require_local_admin(request: Request) -> None:
    client_host = request.client.host if request.client else None
    if client_host not in _LOCAL_HOSTS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "LOCAL_ONLY",
                    "message": "Admin API aceita somente conexoes locais.",
                }
            },
        )
