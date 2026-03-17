"""
auth.py — Autenticación con JWT contra la base de datos.
- GET  /auth/status → {needs_setup: true/false}
- POST /auth/setup  → Crea primer admin (solo si 0 usuarios)
- POST /auth/login  → Login con email+password → JWT con role
"""
import os
import jwt
import bcrypt
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Request, Depends

def get_colombia_time():
    return datetime.utcnow() - timedelta(hours=5)
from sqlalchemy.orm import Session
from ..database import get_db
from ..models.models import User
from ..schemas import SetupRequest, LoginRequest, LoginResponse, AuthStatusResponse
from ..logger_config import get_logger

logger = get_logger("auth")

# ─── Configuración JWT ───
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-in-production")
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24

router = APIRouter(prefix="/auth", tags=["Auth"])


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


def _create_token(user: User) -> str:
    expire = get_colombia_time() + timedelta(hours=TOKEN_EXPIRE_HOURS)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
        "exp": expire,
        "iat": get_colombia_time(),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


# ─── Endpoints ───

@router.get("/status", response_model=AuthStatusResponse)
def auth_status(db: Session = Depends(get_db)):
    """Devuelve si la app necesita setup inicial (0 usuarios)."""
    count = db.query(User).count()
    return AuthStatusResponse(needs_setup=count == 0)


@router.post("/setup", response_model=LoginResponse)
def setup_admin(data: SetupRequest, db: Session = Depends(get_db)):
    """Crea el primer usuario como admin. Solo funciona si no hay usuarios."""
    count = db.query(User).count()
    if count > 0:
        raise HTTPException(status_code=403, detail="Setup ya completado. Usa /auth/login.")

    logger.info("Setup inicial: creando admin %s (%s)", data.username, data.email)

    admin = User(
        username=data.username,
        email=data.email,
        hashed_password=_hash_password(data.password),
        role="admin",
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)

    token = _create_token(admin)
    logger.info("Admin creado exitosamente: %s", data.email)

    return LoginResponse(
        token=token,
        user_id=admin.id,
        username=admin.username,
        email=admin.email,
        role=admin.role,
        expires_in=TOKEN_EXPIRE_HOURS * 3600,
    )


@router.post("/login", response_model=LoginResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    """Login con email+password contra la tabla User."""
    logger.info("Intento de login: %s", data.email)

    user = db.query(User).filter(User.email == data.email).first()
    if not user:
        logger.warning("Login fallido: email no encontrado (%s)", data.email)
        raise HTTPException(status_code=401, detail="Credenciales inválidas")

    if not _verify_password(data.password, user.hashed_password):
        logger.warning("Login fallido: contraseña incorrecta para %s", data.email)
        raise HTTPException(status_code=401, detail="Credenciales inválidas")

    token = _create_token(user)
    logger.info("Login exitoso: %s (role=%s)", data.email, user.role)

    return LoginResponse(
        token=token,
        user_id=user.id,
        username=user.username,
        email=user.email,
        role=user.role,
        expires_in=TOKEN_EXPIRE_HOURS * 3600,
    )


# ─── Verificación de token ───

def verify_token(token: str) -> dict:
    """Verifica un JWT y devuelve el payload con user_id, email, role."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token inválido")


def get_current_user_from_token(request: Request) -> dict:
    """Extrae el usuario del token JWT en el request. Útil para endpoints."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="No autenticado")
    token = auth_header.split("Bearer ", 1)[1]
    return verify_token(token)


# ─── Middleware ───

PUBLIC_PATHS = {"/", "/health", "/auth/login", "/auth/setup", "/auth/status", "/docs", "/openapi.json", "/redoc"}


async def auth_middleware(request: Request, call_next):
    """Middleware que protege todas las rutas excepto las públicas."""
    path = request.url.path

    # Allow static files and SPA routes
    if path in PUBLIC_PATHS or request.method == "OPTIONS" or path.startswith("/assets"):
        return await call_next(request)

    # If no auth header and frontend exists, serve the SPA (non-API routes)
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        # Check if this is an API route or a frontend route
        api_prefixes = ("/users", "/config", "/bot", "/stats", "/logs")
        if any(path.startswith(p) for p in api_prefixes):
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=401, content={"detail": "No autenticado"})
        # Non-API route without auth = let it through (SPA will handle)
        return await call_next(request)

    token = auth_header.split("Bearer ", 1)[1]
    try:
        verify_token(token)
    except HTTPException as e:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=401, content={"detail": e.detail})

    return await call_next(request)
