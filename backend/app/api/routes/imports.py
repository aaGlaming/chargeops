from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
from fastapi.responses import StreamingResponse

from app.api.routes.auth import get_current_user
from app.db import get_db
from app.errors import AppError
from app.schemas.auth import UserSummary
from app.schemas.imports import DatasetType, ImportBatchDetail, ImportBatchListResponse, ImportConfirmRequest, ImportPreviewResponse
from app.services.auth import UserContext, require_permission
from app.services.imports import get_batch, import_rows, list_batches, preview_upload, rollback_batch


router = APIRouter(prefix="/imports", tags=["imports"])


@router.post("/preview", response_model=ImportPreviewResponse, summary="Preview and validate a business data file")
async def preview_import(
    file: UploadFile = File(...),
    dataset_type: DatasetType = Form(...),
    user: UserContext = Depends(get_current_user),
    session=Depends(get_db),
) -> ImportPreviewResponse:
    require_permission(user, "import.read", session=session)
    if not file.filename or file.filename.lower().split(".")[-1] not in {"csv", "json", "geojson"}:
        raise AppError("INVALID_IMPORT_FILE_TYPE", "仅支持 CSV、JSON 和 GeoJSON 文件", status_code=400)
    content = await file.read(25 * 1024 * 1024 + 1)
    if len(content) > 25 * 1024 * 1024:
        raise AppError("IMPORT_FILE_TOO_LARGE", "导入文件不能超过 25 MB", status_code=413)
    try:
        return preview_upload(dataset_type=dataset_type, file_name=file.filename, content=content)
    except (ValueError, UnicodeDecodeError) as exc:
        raise AppError("IMPORT_PREVIEW_FAILED", str(exc), status_code=400) from exc


@router.post("", response_model=ImportBatchDetail, status_code=status.HTTP_201_CREATED, summary="Confirm and persist a business data import")
def confirm_import(request: ImportConfirmRequest, user: UserContext = Depends(get_current_user), session=Depends(get_db)) -> ImportBatchDetail:
    try:
        result = import_rows(session, user, request)
        session.commit()
        return result
    except AppError:
        session.rollback()
        raise
    except Exception as exc:
        session.rollback()
        raise AppError("IMPORT_BATCH_FAILED", str(exc), status_code=400) from exc


@router.get("", response_model=ImportBatchListResponse, summary="List business data import batches")
def imports(page: int = Query(default=1, ge=1), page_size: int = Query(default=25, ge=1, le=200), user: UserContext = Depends(get_current_user), session=Depends(get_db)) -> ImportBatchListResponse:
    return list_batches(session, user, page=page, page_size=page_size)


@router.get("/{batch_id}", response_model=ImportBatchDetail, summary="Get an import batch detail")
def import_detail(batch_id: int, user: UserContext = Depends(get_current_user), session=Depends(get_db)) -> ImportBatchDetail:
    result = get_batch(session, batch_id, user=user)
    if result is None:
        raise AppError("IMPORT_BATCH_NOT_FOUND", "导入批次不存在", status_code=404)
    return result


@router.get("/{batch_id}/errors.csv", summary="Download import row errors")
def import_errors_csv(batch_id: int, user: UserContext = Depends(get_current_user), session=Depends(get_db)) -> StreamingResponse:
    batch = get_batch(session, batch_id, user=user)
    if batch is None:
        raise AppError("IMPORT_BATCH_NOT_FOUND", "导入批次不存在", status_code=404)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["row", "field", "error_code", "message", "raw_payload"])
    for item in batch.errors:
        writer.writerow([item.get("row", ""), item.get("field", ""), item.get("error_code", ""), item.get("message", ""), item.get("raw_payload", "")])
    return StreamingResponse(iter([output.getvalue().encode("utf-8-sig")]), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="import-{batch_id}-errors.csv"'})


@router.post("/{batch_id}/rollback", response_model=ImportBatchDetail, summary="Roll back an import batch")
def rollback_import(batch_id: int, user: UserContext = Depends(get_current_user), session=Depends(get_db)) -> ImportBatchDetail:
    try:
        result = rollback_batch(session, batch_id, user)
        session.commit()
        return result
    except AppError:
        session.rollback()
        raise
    except Exception as exc:
        session.rollback()
        raise AppError("IMPORT_ROLLBACK_FAILED", str(exc), status_code=400) from exc

