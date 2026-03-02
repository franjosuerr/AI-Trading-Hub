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
    ai_provider = Column(String, default="groq")
    openai_api_key = Column(String, nullable=True)
    groq_api_key = Column(String, nullable=True)
    google_api_key = Column(String, nullable=True)
    ollama_host = Column(String, default="http://localhost:11434")
    
    # Modelos por proveedor
    openai_model = Column(String, default="gpt-4o-mini")
    groq_model = Column(String, default="llama-3.1-8b-instant")
    gemini_model = Column(String, default="gemini-2.0-flash")
    ollama_model = Column(String, default="llama2")
    
    timeframe = Column(String, default="15m")
    interval = Column(Integer, default=300)
    test_mode = Column(Boolean, default=False)
    pairs = Column(String, default="SOL/USDT,ETH/USDT")
    
    # Parámetros de trading
    candle_count = Column(Integer, default=210)
    prompt_candles = Column(Integer, default=10)
    confidence_threshold = Column(Float, default=0.7)
    stop_loss_percent = Column(Float, default=2.0)
    max_trades_per_day = Column(Integer, default=5)
    pair_delay = Column(Integer, default=2)
    
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

    owner = relationship("User", back_populates="trades")
