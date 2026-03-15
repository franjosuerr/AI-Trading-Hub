from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from ..database import Base

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
    created_at = Column(DateTime, default=datetime.utcnow)

    trades = relationship("Trade", back_populates="owner")

class GlobalConfig(Base):
    __tablename__ = "global_config"

    id = Column(Integer, primary_key=True, index=True)
    
    timeframe = Column(String, default="15m")
    interval = Column(Integer, default=300)
    test_mode = Column(Boolean, default=False)
    pairs = Column(String, default="SOL/USDT,ETH/USDT,BTC/USDT,XRP/USDT")
    
    # Parámetros de trading
    candle_count = Column(Integer, default=210)
    stop_loss_percent = Column(Float, default=3.0)
    max_trades_per_day = Column(Integer, default=5)
    pair_delay = Column(Integer, default=2)
    max_exposure_percent = Column(Float, default=80.0)
    cooldown_minutes = Column(Integer, default=120)
    
    # Parámetros Estrategia EMA
    ema_fast = Column(Integer, default=7)
    ema_slow = Column(Integer, default=30)
    adx_period = Column(Integer, default=14)
    adx_threshold = Column(Integer, default=25)
    invest_percentage = Column(Float, default=25.0)
    invest_percentage_ranging = Column(Float, default=15.0)  # % para estrategia de rango (mean reversion)
    
    # Parámetros Pro
    trailing_stop_activation = Column(Float, default=1.5)  # % de profit a partir del cual se prende el trailing stop
    trailing_stop_distance = Column(Float, default=0.5)    # % de distancia del máximo para vender
    macro_timeframe = Column(String, default="1h")         # Temporalidad para filtrado macro
    
    # Logs
    log_level = Column(String, default="INFO")

class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    pair = Column(String)
    side = Column(String) # buy / sell
    amount = Column(Float)
    price = Column(Float)
    timestamp = Column(DateTime, default=datetime.utcnow)
    order_id = Column(String)
    simulated = Column(Boolean)
    profit = Column(Float, default=0.0) # Para registrar ganancias al cerrar (sell)
    max_price_reached = Column(Float, default=0.0) # Para Trailing Stop Loss

    owner = relationship("User", back_populates="trades")
