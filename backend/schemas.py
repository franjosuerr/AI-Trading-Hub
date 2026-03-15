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

class GlobalConfigBase(BaseModel):
    timeframe: str
    interval: int
    test_mode: bool
    pairs: str
    candle_count: int

    stop_loss_percent: float
    max_trades_per_day: int
    pair_delay: int
    max_exposure_percent: float
    cooldown_minutes: int
    log_level: str
    
    ema_fast: int
    ema_slow: int
    adx_period: int
    adx_threshold: int
    invest_percentage: float
    invest_percentage_ranging: float
    
    trailing_stop_activation: float
    trailing_stop_distance: float
    macro_timeframe: str
    risk_profile: str
    
    use_vwap_filter: bool
    use_daily_open_filter: bool

class GlobalConfigResponse(GlobalConfigBase):
    id: int

    class Config:
        from_attributes = True

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
