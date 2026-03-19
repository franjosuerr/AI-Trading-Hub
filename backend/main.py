from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from .database import engine, get_db, Base
from .models import User, Trade
from .logger_config import setup_backend_logging, get_logger, cleanup_old_logs
from .api.auth import auth_middleware
import asyncio
import httpx
import os

# Configurar logs
setup_backend_logging()
logger = get_logger("api")

logger.info("Iniciando aplicación FastAPI...")

# ─── Migración Automática de Base de Datos ───
def auto_migrate_db():
    """Migra columnas de configuración al modelo User (antes estaban en global_config)."""
    import sqlite3
    db_path = os.getenv("DATABASE_URL", "sqlite:///./data/trading_bot.db").replace("sqlite:///", "")
    if not os.path.exists(db_path):
        return

    logger.info("Ejecutando migraciones automáticas de base de datos...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Columnas de configuración que ahora viven en la tabla users
    user_columns = [
        ("timeframe", "VARCHAR DEFAULT '15m'"),
        ("interval", "INTEGER DEFAULT 300"),
        ("test_mode", "BOOLEAN DEFAULT 0"),
        ("pairs", "VARCHAR DEFAULT 'SOL/USDT,ETH/USDT,BTC/USDT,XRP/USDT'"),
        ("candle_count", "INTEGER DEFAULT 350"),
        ("stop_loss_percent", "FLOAT DEFAULT 3.0"),
        ("max_trades_per_day", "INTEGER DEFAULT 5"),
        ("pair_delay", "INTEGER DEFAULT 2"),
        ("max_exposure_percent", "FLOAT DEFAULT 80.0"),
        ("cooldown_minutes", "INTEGER DEFAULT 120"),
        ("ema_fast", "INTEGER DEFAULT 7"),
        ("ema_slow", "INTEGER DEFAULT 30"),
        ("adx_period", "INTEGER DEFAULT 14"),
        ("adx_threshold", "INTEGER DEFAULT 25"),
        ("invest_percentage", "FLOAT DEFAULT 25.0"),
        ("invest_percentage_ranging", "FLOAT DEFAULT 15.0"),
        ("trailing_stop_activation", "FLOAT DEFAULT 1.5"),
        ("trailing_stop_distance", "FLOAT DEFAULT 0.5"),
        ("macro_timeframe", "VARCHAR DEFAULT '1h'"),
        ("log_level", "VARCHAR DEFAULT 'INFO'"),
        ("risk_profile", "VARCHAR DEFAULT 'conservador'"),
        ("use_vwap_filter", "BOOLEAN DEFAULT 0"),
        ("use_daily_open_filter", "BOOLEAN DEFAULT 0"),
        ("schedule_enabled", "BOOLEAN DEFAULT 0"),
        ("schedule_start_hour", "INTEGER DEFAULT 22"),
        ("schedule_end_hour", "INTEGER DEFAULT 6"),
        ("schedule_risk_profile", "VARCHAR DEFAULT 'suave'"),
    ]

    for col_name, col_def in user_columns:
        try:
            cursor.execute(f'ALTER TABLE users ADD COLUMN {col_name} {col_def}')
            logger.info("Columna '%s' agregada a users.", col_name)
        except sqlite3.OperationalError:
            pass  # Ya existe

    # Eliminar tabla global_config legacy si existe
    try:
        cursor.execute('DROP TABLE IF EXISTS global_config')
        logger.info("Tabla legacy 'global_config' eliminada.")
    except Exception:
        pass

    conn.commit()
    conn.close()

auto_migrate_db()

# Crear tablas
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Trading Bot API")

# ─── Limpieza diaria de trades antiguos (medianoche hora Colombia) ───
async def daily_cleanup():
    """Elimina trades con más de 90 días todos los días a las 00:00 hora Colombia."""
    from .database import SessionLocal
    from datetime import datetime, timedelta
    while True:
        now_col = datetime.utcnow() - timedelta(hours=5)
        next_midnight = (now_col + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        seconds_until_midnight = (next_midnight - now_col).total_seconds()
        await asyncio.sleep(seconds_until_midnight)

        _db = SessionLocal()
        try:
            cutoff = datetime.utcnow() - timedelta(hours=5) - timedelta(days=90)
            deleted = _db.query(Trade).filter(Trade.timestamp < cutoff).delete()
            _db.commit()
            logger.info(f"[Limpieza diaria] {deleted} trades eliminados (>90 días).")
        except Exception as e:
            logger.error(f"[Limpieza diaria] Error: {e}")
            _db.rollback()
        finally:
            _db.close()


# ─── Keep-Alive (evitar que Render duerma la app) ───
async def keep_alive():
    """Ping a sí mismo cada 10 minutos para evitar que Render duerma la instancia."""
    render_url = os.getenv("RENDER_EXTERNAL_URL")
    if not render_url:
        logger.info("RENDER_EXTERNAL_URL no definida, keep-alive desactivado (entorno local).")
        return
    health_url = f"{render_url}/health"
    logger.info(f"Keep-alive activado: ping cada 10 min a {health_url}")
    async with httpx.AsyncClient() as client:
        while True:
            await asyncio.sleep(600)  # 10 minutos
            try:
                resp = await client.get(health_url, timeout=10)
                logger.debug(f"Keep-alive ping: {resp.status_code}")
            except Exception as e:
                logger.warning(f"Keep-alive error: {e}")

@app.on_event("startup")
async def startup_event():
    # Limpiar logs con más de 90 días
    cleanup_old_logs(max_days=90)
    logger.info("Limpieza de logs antiguos completada.")

    # Limpiar trades con más de 90 días de la BD
    from .database import SessionLocal
    from datetime import datetime, timedelta
    _db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(hours=5) - timedelta(days=90)  # hora Colombia
        deleted = _db.query(Trade).filter(Trade.timestamp < cutoff).delete()
        _db.commit()
        if deleted:
            logger.info(f"Limpieza BD: {deleted} trades eliminados (>90 días).")
    except Exception as e:
        logger.error(f"Error limpiando trades antiguos: {e}")
        _db.rollback()
    finally:
        _db.close()

    logger.info("Sincronizando bots activos desde la base de datos...")
    from .database import SessionLocal
    from bot.bot_manager import bot_manager
    
    db = SessionLocal()
    try:
        active_users = db.query(User).filter(User.is_active == True).all()
        for user in active_users:
            logger.info(f"Reiniciando bot para usuario: {user.username}")
            await bot_manager.start_bot(user.id)
        logger.info(f"Sincronización completada. {len(active_users)} bots iniciados.")
    except Exception as e:
        logger.error(f"Error durante la sincronización de inicio: {e}")
    finally:
        db.close()

    # Iniciar keep-alive y limpieza diaria
    asyncio.create_task(keep_alive())
    asyncio.create_task(daily_cleanup())
    logger.info("Tarea de limpieza diaria programada para las 00:00 hora Colombia.")

# Configurar CORS para el frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Middleware de autenticación JWT (se ejecuta DESPUÉS del CORS)
@app.middleware("http")
async def jwt_auth(request, call_next):
    return await auth_middleware(request, call_next)

@app.get("/health")
def health_check():
    return {"status": "healthy"}

# Incluir routers API
from .api import users, control, stats, logs, auth
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(control.router)
app.include_router(stats.router)
app.include_router(logs.router)

# ─── Servir Frontend Estático ───
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")

if os.path.exists(FRONTEND_DIR):
    # Servir assets estáticos (JS, CSS, imágenes)
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIR, "assets")), name="static_assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Catch-all: sirve index.html para cualquier ruta del SPA de React."""
        file_path = os.path.join(FRONTEND_DIR, full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))
else:
    @app.get("/")
    def read_root():
        return {"status": "online", "message": "Trading Bot API is running. Frontend not built yet."}

