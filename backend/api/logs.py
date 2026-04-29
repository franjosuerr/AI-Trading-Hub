import os
from datetime import date

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..logger_config import setup_frontend_logger, BOT_LOG_DIR, get_user_analysis_log_path
from .auth import get_current_user_from_token

# Logger dedicado → logs/frontend.log
frontend_logger = setup_frontend_logger()

router = APIRouter(prefix="/logs", tags=["Logs"])

class LogMessage(BaseModel):
    level: str
    message: str
    context: dict = {}

@router.post("/")
async def receive_frontend_logs(log: LogMessage, request: Request):
    client_host = request.client.host
    log_msg = f"{log.message} | Context: {log.context} | IP: {client_host}"
    
    if log.level.lower() == "error":
        frontend_logger.error(log_msg)
    elif log.level.lower() == "warning":
        frontend_logger.warning(log_msg)
    else:
        frontend_logger.info(log_msg)
        
    return {"status": "ok"}


@router.get("/bot/{user_id}/download")
async def download_bot_log(
    user_id: int,
    request: Request,
    log_date: str = Query(None, description="Fecha del log (YYYY-MM-DD). Si no se envía, se usa hoy.")
):
    """Descarga el archivo .log del bot de un usuario para una fecha dada."""
    # --- Auth ---
    current = get_current_user_from_token(request)
    if current["role"] != "admin" and current["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Sin permisos para descargar estos logs")

    # --- Resolver archivo ---
    today_str = date.today().strftime("%Y-%m-%d")
    base_file = os.path.join(BOT_LOG_DIR, f"user_{user_id}.log")

    if log_date is None or log_date == today_str:
        # Archivo del día actual (sin sufijo de fecha)
        filepath = base_file
        file_date = today_str
    else:
        # Archivo rotado de un día anterior
        filepath = f"{base_file}.{log_date}"
        file_date = log_date

    if not os.path.isfile(filepath):
        raise HTTPException(status_code=404, detail=f"No se encontró log para la fecha {file_date}")

    download_name = f"bot_user_{user_id}_{file_date}.log"

    return FileResponse(
        path=filepath,
        media_type="text/plain",
        filename=download_name,
    )


@router.get("/bot/{user_id}/analysis/download")
async def download_bot_analysis_log(user_id: int, request: Request):
    """Descarga el log analítico (único fichero) de un usuario."""
    current = get_current_user_from_token(request)
    if current["role"] != "admin" and current["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Sin permisos para descargar estos logs")

    filepath = get_user_analysis_log_path(user_id)
    if not os.path.isfile(filepath):
        raise HTTPException(status_code=404, detail="No se encontró log analítico para este usuario")

    return FileResponse(
        path=filepath,
        media_type="text/plain",
        filename=f"bot_user_{user_id}_analysis.log",
    )
