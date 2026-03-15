from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from ..database import get_db
from ..models.models import GlobalConfig, User
from ..schemas import GlobalConfigBase, GlobalConfigResponse
from ..logger_config import get_logger
from .auth import get_current_user_from_token

logger = get_logger("config_api")

router = APIRouter(prefix="/config", tags=["Configuration"])

@router.get("/", response_model=GlobalConfigResponse)
def get_config(db: Session = Depends(get_db)):
    config = db.query(GlobalConfig).first()
    if not config:
        config = GlobalConfig(
            test_mode=True,
            pairs="SOL/USDT,ETH/USDT",
            timeframe="15m",
            interval=300,
            candle_count=350,
            pair_delay=2,
            max_trades_per_day=5,
            max_exposure_percent=10.0,
            cooldown_minutes=120,
            ema_fast=7,
            ema_slow=30,
            adx_period=14,
            adx_threshold=25,
            invest_percentage=75.0,
            trailing_stop_activation=1.5,
            trailing_stop_distance=0.5,
            macro_timeframe="1h"
        )
        db.add(config)
        db.commit()
        db.refresh(config)
    return config

@router.post("/", response_model=GlobalConfigResponse)
async def update_config(config_update: GlobalConfigBase, request: Request, db: Session = Depends(get_db)):
    """Actualizar config global. Solo admin."""
    current = get_current_user_from_token(request)
    if current["role"] != "admin":
        raise HTTPException(status_code=403, detail="Solo el administrador puede modificar la configuración global")

    config = db.query(GlobalConfig).first()
    if not config:
        config = GlobalConfig()
        db.add(config)
    
    for key, value in config_update.dict().items():
        setattr(config, key, value)
    
    db.commit()
    db.refresh(config)

    # Reiniciar TODOS los bots activos
    from bot.bot_manager import bot_manager
    active_users = db.query(User).filter(User.is_active == True).all()
    restarted = 0
    for user in active_users:
        try:
            logger.info(f"Reiniciando bot de {user.username} por cambio de configuración global...")
            await bot_manager.stop_bot(user.id)
            await bot_manager.start_bot(user.id)
            restarted += 1
        except Exception as e:
            logger.warning(f"Error al reiniciar bot de {user.username}: {e}")
    
    if restarted > 0:
        logger.info(f"Configuración global actualizada. {restarted} bot(s) reiniciado(s).")

    return config
