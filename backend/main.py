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
            cursor.execute('ALTER TABLE global_config ADD COLUMN max_exposure_percent FLOAT DEFAULT 10.0')
            logger.info("Columna 'max_exposure_percent' agregada.")
        except sqlite3.OperationalError:
            pass # Ya existe
            
        try:
            cursor.execute('ALTER TABLE global_config ADD COLUMN cooldown_minutes INTEGER DEFAULT 120')
            logger.info("Columna 'cooldown_minutes' agregada.")
        except sqlite3.OperationalError:
            pass # Ya existe
            
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

