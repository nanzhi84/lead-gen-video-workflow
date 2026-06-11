from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request, Response, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse

from apps.api.dependencies import require_role
from apps.api.services import core as service
from packages.core import contracts as c

router = APIRouter()

@router.get("/api/health", response_model=c.OkResponse)
def health(request: Request) -> c.OkResponse:

    return service.health(request)


@router.get("/metrics", response_class=PlainTextResponse)
def metrics(request: Request) -> str:

    return service.metrics(request)
