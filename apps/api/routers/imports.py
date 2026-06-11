from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request, Response, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse

from apps.api.dependencies import require_role
from apps.api.services import imports as service
from packages.core import contracts as c

router = APIRouter()

@router.post("/api/import/batches", response_model=c.ImportBatchReport, status_code=202)
def import_batch(payload: c.CreateImportBatchRequest, request: Request) -> c.ImportBatchReport:
    require_role(request, c.UserRole.operator)
    return service.import_batch(payload, request)


@router.get("/api/import/batches/{batch_id}", response_model=c.ImportBatchReport)
def import_batch_detail(request: Request, batch_id: str) -> c.ImportBatchReport:

    return service.import_batch_detail(request, batch_id)
