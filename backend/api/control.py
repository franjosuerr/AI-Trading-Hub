from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from ..database import get_db
from ..models.models import User
from bot.bot_manager import bot_manager
from ..logger_config import get_logger
from .auth import get_current_user_from_token

logger = get_logger("control_api")

router = APIRouter(prefix="/bot", tags=["Control"])

@router.post("/{user_id}/start")
async def start_user_bot(user_id: int, request: Request, db: Session = Depends(get_db)):
    """Admin: inicia cualquier bot. User: solo su bot."""
    current = get_current_user_from_token(request)
    if current["role"] != "admin" and int(current["sub"]) != user_id:
        raise HTTPException(status_code=403, detail="Solo puedes controlar tu propio bot")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    started = await bot_manager.start_bot(user_id)
    if not started:
        return {"message": f"Bot for user {user.username} is already running"}
    
    user.is_active = True
    db.commit()
    return {"message": f"Bot for user {user.username} started"}

@router.post("/{user_id}/stop")
async def stop_user_bot(user_id: int, request: Request, db: Session = Depends(get_db)):
    """Admin: detiene cualquier bot. User: solo su bot."""
    current = get_current_user_from_token(request)
    if current["role"] != "admin" and int(current["sub"]) != user_id:
        raise HTTPException(status_code=403, detail="Solo puedes controlar tu propio bot")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    stopped = await bot_manager.stop_bot(user_id)
    
    if user.is_active or stopped:
        user.is_active = False
        db.commit()
        logger.info(f"Estado de usuario {user.username} sincronizado a INACTIVO en DB")
    
    if not stopped:
        return {"message": f"Bot for user {user.username} was not in memory, but DB state is now synchronized to STOPPED"}
        
    return {"message": f"Bot for user {user.username} stopped successfully"}

@router.get("/status")
def get_bots_status():
    return {"active_bots_count": len(bot_manager.active_bots), "active_user_ids": list(bot_manager.active_bots.keys())}
