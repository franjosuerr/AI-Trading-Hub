from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class UserBase(BaseModel):
    username: str
    email: str
    coinex_api_key: Optional[str] = None
    coinex_secret: Optional[str] = None
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None

    # Bot Configurations
    timeframe: str = "15m"
    interval: int = 300
    test_mode: bool = False
    pairs: str = "SOL/USDT,ETH/USDT,BTC/USDT,XRP/USDT"
    candle_count: int = 350
    stop_loss_percent: float = 3.0
    max_trades_per_day: int = 5
    pair_delay: int = 2
    max_exposure_percent: float = 80.0
    cooldown_minutes: int = 120
    log_level: str = "INFO"
    
    ema_fast: int = 7
    ema_slow: int = 30
    adx_period: int = 14
    adx_threshold: int = 25
    invest_percentage: float = 25.0
    invest_percentage_ranging: float = 15.0
    
    trailing_stop_activation: float = 1.5
    trailing_stop_distance: float = 0.5
    macro_timeframe: str = "1h"
    risk_profile: str = "conservador"
    
    use_vwap_filter: bool = False
    use_daily_open_filter: bool = False

class UserCreate(UserBase):
    password: str

class UserUpdate(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None
    coinex_api_key: Optional[str] = None
    coinex_secret: Optional[str] = None
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    password: Optional[str] = None  # Para cambiar contraseña
    
    # Bot Configurations
    timeframe: Optional[str] = None
    interval: Optional[int] = None
    test_mode: Optional[bool] = None
    pairs: Optional[str] = None
    candle_count: Optional[int] = None
    stop_loss_percent: Optional[float] = None
    max_trades_per_day: Optional[int] = None
    pair_delay: Optional[int] = None
    max_exposure_percent: Optional[float] = None
    cooldown_minutes: Optional[int] = None
    log_level: Optional[str] = None
    
    ema_fast: Optional[int] = None
    ema_slow: Optional[int] = None
    adx_period: Optional[int] = None
    adx_threshold: Optional[int] = None
    invest_percentage: Optional[float] = None
    invest_percentage_ranging: Optional[float] = None
    
    trailing_stop_activation: Optional[float] = None
    trailing_stop_distance: Optional[float] = None
    macro_timeframe: Optional[str] = None
    risk_profile: Optional[str] = None
    
    use_vwap_filter: Optional[bool] = None
    use_daily_open_filter: Optional[bool] = None

class UserResponse(UserBase):
    id: int
    role: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True

class SetupRequest(BaseModel):
    username: str
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class LoginResponse(BaseModel):
    token: str
    user_id: int
    username: str
    email: str
    role: str
    expires_in: int  # segundos

class AuthStatusResponse(BaseModel):
    needs_setup: bool



class TradeResponse(BaseModel):
    id: int
    pair: str
    side: str
    amount: float
    price: float
    timestamp: datetime
    order_id: str
    simulated: bool
    profit: float
    max_price_reached: float

    class Config:
        from_attributes = True
