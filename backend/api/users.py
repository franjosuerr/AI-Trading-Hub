from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from ..database import get_db
from sqlalchemy import func
from ..models.models import User, Trade
from ..schemas import UserCreate, UserResponse, UserUpdate
from typing import List
from ..logger_config import get_logger
from .auth import get_current_user_from_token
import bcrypt

logger = get_logger("users_api")

router = APIRouter(prefix="/users", tags=["Users"])


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _user_with_profit(user, db):
    """Agrega total_profit y total_invested_trapped al dict del usuario."""
    profit = db.query(func.sum(Trade.profit)).filter(Trade.user_id == user.id).scalar() or 0.0
    user_dict = {k: v for k, v in user.__dict__.items() if not k.startswith('_')}
    user_dict["total_profit"] = round(float(profit), 4)

    # Calcular total invertido atrapado (posiciones abiertas)
    trades = db.query(Trade).filter(Trade.user_id == user.id).order_by(Trade.timestamp.asc()).all()
    positions = {}
    for t in trades:
        if t.pair not in positions:
            positions[t.pair] = {"amount": 0.0, "total_cost": 0.0}
        if t.side == "buy":
            positions[t.pair]["amount"] += t.amount
            positions[t.pair]["total_cost"] += (t.amount * t.price)
        elif t.side == "sell":
            prev_amount = positions[t.pair]["amount"]
            if prev_amount > 0:
                cost_reduction_ratio = min(t.amount / prev_amount, 1.0)
                positions[t.pair]["total_cost"] -= (positions[t.pair]["total_cost"] * cost_reduction_ratio)
            positions[t.pair]["amount"] -= t.amount
            if positions[t.pair]["amount"] < 0.0001:
                positions[t.pair]["amount"] = 0.0
                positions[t.pair]["total_cost"] = 0.0
    total_trapped = sum(p["total_cost"] for p in positions.values() if p["amount"] > 0.0001)
    user_dict["total_invested_trapped"] = round(total_trapped, 2)

    return user_dict


@router.post("/", response_model=UserResponse)
def create_user(user: UserCreate, request: Request, db: Session = Depends(get_db)):
    """Crear usuario. Solo admin."""
    current = get_current_user_from_token(request)
    if current["role"] != "admin":
        raise HTTPException(status_code=403, detail="Solo el administrador puede crear usuarios")

    # Verificar duplicados
    if db.query(User).filter(User.username == user.username).first():
        raise HTTPException(status_code=400, detail="Username ya registrado")
    if db.query(User).filter(User.email == user.email).first():
        raise HTTPException(status_code=400, detail="Email ya registrado")
    
    # Construir usuario con configs por defecto o desde payload
    user_data = user.dict(exclude={"password"})
    new_user = User(
        hashed_password=_hash_password(user.password),
        role="user",
        **user_data
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    logger.info(f"Usuario creado por admin: {new_user.username} ({new_user.email})")
    return new_user

@router.get("/")
def get_users(request: Request, db: Session = Depends(get_db)):
    """Admin: todos los usuarios. User: solo sí mismo. Incluye total_profit."""
    current = get_current_user_from_token(request)
    if current["role"] == "admin":
        users = db.query(User).all()
    else:
        user = db.query(User).filter(User.id == int(current["sub"])).first()
        users = [user] if user else []
    return [_user_with_profit(u, db) for u in users]

@router.get("/me", response_model=UserResponse)
def get_current_user(request: Request, db: Session = Depends(get_db)):
    """Obtener datos del usuario actual."""
    current = get_current_user_from_token(request)
    user = db.query(User).filter(User.id == int(current["sub"])).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@router.get("/{user_id}", response_model=UserResponse)
def get_user(user_id: int, request: Request, db: Session = Depends(get_db)):
    """Admin: cualquier usuario. User: solo sí mismo."""
    current = get_current_user_from_token(request)
    if current["role"] != "admin" and int(current["sub"]) != user_id:
        raise HTTPException(status_code=403, detail="No tienes acceso a este usuario")

    db_user = db.query(User).filter(User.id == user_id).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    return db_user

@router.put("/{user_id}", response_model=UserResponse)
async def update_user(user_id: int, user_update: UserUpdate, request: Request, db: Session = Depends(get_db)):
    """Admin: editar cualquiera. User: solo sí mismo."""
    current = get_current_user_from_token(request)
    if current["role"] != "admin" and int(current["sub"]) != user_id:
        raise HTTPException(status_code=403, detail="No tienes acceso a este usuario")

    db_user = db.query(User).filter(User.id == user_id).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    update_data = user_update.dict(exclude_unset=True)
    
    # Si viene password, hashearla
    if "password" in update_data and update_data["password"]:
        update_data["hashed_password"] = _hash_password(update_data.pop("password"))
    else:
        update_data.pop("password", None)

    for key, value in update_data.items():
        setattr(db_user, key, value)
    
    db.commit()
    db.refresh(db_user)

    # Si el bot está activo, reiniciarlo
    if db_user.is_active:
        from bot.bot_manager import bot_manager
        try:
            logger.info(f"Reiniciando bot de {db_user.username} por cambio de configuración...")
            await bot_manager.stop_bot(user_id)
            await bot_manager.start_bot(user_id)
            logger.info(f"Bot de {db_user.username} reiniciado.")
        except Exception as e:
            logger.warning(f"Error al reiniciar bot de {db_user.username}: {e}")

    return db_user

@router.delete("/{user_id}")
def delete_user(user_id: int, request: Request, db: Session = Depends(get_db)):
    """Solo admin puede eliminar usuarios."""
    current = get_current_user_from_token(request)
    if current["role"] != "admin":
        raise HTTPException(status_code=403, detail="Solo el administrador puede eliminar usuarios")

    db_user = db.query(User).filter(User.id == user_id).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(db_user)
    db.commit()
    logger.info(f"Usuario eliminado por admin: {db_user.username}")
    return {"message": "User deleted"}
