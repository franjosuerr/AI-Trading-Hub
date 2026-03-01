from fastapi import APIRouter, Request
from pydantic import BaseModel
from ..logger_config import setup_frontend_logger

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
