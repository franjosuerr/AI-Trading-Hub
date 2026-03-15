from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from .database import engine, get_db, Base
from .models import User, GlobalConfig, Trade
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
    import sqlite3
    db_path = os.getenv("DATABASE_URL", "sqlite:///./data/trading_bot.db").replace("sqlite:///", "")
    if os.path.exists(db_path):
        logger.info("Ejecutando migraciones automáticas de base de datos...")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('ALTER TABLE global_config ADD COLUMN max_exposure_percent FLOAT DEFAULT 80.0')
            logger.info("Columna 'max_exposure_percent' agregada.")
        except sqlite3.OperationalError:
            pass # Ya existe
        
        # Corregir valor legacy: 10% bloqueaba compras con invest_percentage=75%
        try:
            cursor.execute('UPDATE global_config SET max_exposure_percent = 80.0 WHERE max_exposure_percent = 10.0')
            if cursor.rowcount > 0:
                logger.info("max_exposure_percent actualizado de 10.0 a 80.0 (%d registro(s)).", cursor.rowcount)
        except Exception:
            pass
            
        try:
            cursor.execute('ALTER TABLE global_config ADD COLUMN cooldown_minutes INTEGER DEFAULT 120')
            logger.info("Columna 'cooldown_minutes' agregada.")
        except sqlite3.OperationalError:
            pass # Ya existe
        
        # Migración: columna invest_percentage_ranging para estrategia de rango
        try:
            cursor.execute('ALTER TABLE global_config ADD COLUMN invest_percentage_ranging FLOAT DEFAULT 15.0')
            logger.info("Columna 'invest_percentage_ranging' agregada.")
        except sqlite3.OperationalError:
            pass # Ya existe
        
        # Migración: actualizar pares para incluir BTC y XRP
        try:
            cursor.execute("UPDATE global_config SET pairs = 'SOL/USDT,ETH/USDT,BTC/USDT,XRP/USDT' WHERE pairs = 'SOL/USDT,ETH/USDT'")
            if cursor.rowcount > 0:
                logger.info("Pares actualizados: añadidos BTC/USDT y XRP/USDT.")
        except Exception:
            pass
            
        # Migración: Perfil de Riesgo
        try:
            cursor.execute("ALTER TABLE global_config ADD COLUMN risk_profile VARCHAR DEFAULT 'conservador'")
            logger.info("Columna 'risk_profile' agregada.")
        except sqlite3.OperationalError:
            pass # Ya existe
            
        # Migración: Intraday Filters
        try:
            cursor.execute('ALTER TABLE global_config ADD COLUMN use_vwap_filter BOOLEAN DEFAULT 0')
            cursor.execute('ALTER TABLE global_config ADD COLUMN use_daily_open_filter BOOLEAN DEFAULT 0')
            logger.info("Columnas 'use_vwap_filter' y 'use_daily_open_filter' agregadas.")
        except sqlite3.OperationalError:
            pass # Ya existen
        
        # Migración: ajustar invest_percentage de 75% a 25% (position sizing conservador)
        try:
            cursor.execute('UPDATE global_config SET invest_percentage = 25.0 WHERE invest_percentage = 75.0')
            if cursor.rowcount > 0:
                logger.info("invest_percentage ajustado de 75%% a 25%% (position sizing profesional).")
        except Exception:
            pass
        
        # Migración: ajustar stop_loss de 2% a 3%
        try:
            cursor.execute('UPDATE global_config SET stop_loss_percent = 3.0 WHERE stop_loss_percent = 2.0')
            if cursor.rowcount > 0:
                logger.info("stop_loss_percent ajustado de 2%% a 3%%.")
        except Exception:
            pass
            
        conn.commit()
        conn.close()

auto_migrate_db()

# Crear tablas
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Trading Bot API")

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
    # Limpiar logs con más de 30 días
    cleanup_old_logs(max_days=30)
    logger.info("Limpieza de logs antiguos completada.")

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

    # Iniciar keep-alive
    asyncio.create_task(keep_alive())

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
from .api import users, config, control, stats, logs, auth
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(config.router)
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

