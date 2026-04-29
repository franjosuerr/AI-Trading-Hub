from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime, timedelta
from ..database import Base

def get_colombia_time():
    return datetime.utcnow() - timedelta(hours=5)

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    role = Column(String, default="user")  # "admin" o "user"
    
    # CoinEx Config
    coinex_api_key = Column(String, nullable=True)
    coinex_secret = Column(String, nullable=True)
    
    # Telegram Config
    telegram_bot_token = Column(String, nullable=True)
    telegram_chat_id = Column(String, nullable=True)
    
    is_active = Column(Boolean, default=False) # Si el bot de este usuario está corriendo
    created_at = Column(DateTime, default=get_colombia_time)

    # ------------------
    # Configuraciones Individuales del Bot
    # ------------------
    timeframe = Column(String, default="15m")
    interval = Column(Integer, default=300)
    test_mode = Column(Boolean, default=True)
    pairs = Column(String, default="BTC/USDT,ETH/USDT,SOL/USDT")
    
    # Parámetros de trading
    candle_count = Column(Integer, default=350)
    stop_loss_percent = Column(Float, default=3.0)
    max_trades_per_day = Column(Integer, default=4)
    pair_delay = Column(Integer, default=2)
    max_exposure_percent = Column(Float, default=40.0)
    cooldown_minutes = Column(Integer, default=180)
    
    # Parámetros Estrategia EMA
    ema_fast = Column(Integer, default=7)
    ema_slow = Column(Integer, default=30)
    adx_period = Column(Integer, default=14)
    adx_threshold = Column(Integer, default=28)
    invest_percentage = Column(Float, default=10.0)
    invest_percentage_ranging = Column(Float, default=10.0)
    
    # Parámetros Pro
    trailing_stop_activation = Column(Float, default=2.5)
    trailing_stop_distance = Column(Float, default=0.55)
    macro_timeframe = Column(String, default="1h")
    
    # Logs / Status
    log_level = Column(String, default="INFO")
    risk_profile = Column(String, default="conservador")

    # Day Trading Intraday Filters
    use_vwap_filter = Column(Boolean, default=True)
    use_daily_open_filter = Column(Boolean, default=False)

    # Fee del exchange (porcentaje, 0.1 = 0.1% para CoinEx limit/maker)
    fee_rate = Column(Float, default=0.1)

    # Horario Nocturno / Schedule
    schedule_enabled = Column(Boolean, default=False)
    schedule_start_hour = Column(Integer, default=22)  # 10 PM
    schedule_end_hour = Column(Integer, default=6)      # 6 AM
    schedule_risk_profile = Column(String, default="suave")

    # Relaciones
    trades = relationship("Trade", back_populates="owner")

class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    pair = Column(String)
    side = Column(String) # buy / sell
    amount = Column(Float)
    price = Column(Float)
    timestamp = Column(DateTime, default=get_colombia_time)
    order_id = Column(String)
    simulated = Column(Boolean)
    profit = Column(Float, default=0.0) # Para registrar ganancias al cerrar (sell)
    max_price_reached = Column(Float, default=0.0) # Para Trailing Stop Loss
    partial_exit_done = Column(Boolean, default=False) # Si ya se ejecutó venta parcial (TP1)

    owner = relationship("User", back_populates="trades")
