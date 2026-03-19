from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from collections import defaultdict
from datetime import datetime, timedelta
import ccxt
import time

from ..database import get_db
from ..models.models import User, Trade
from bot.bot_manager import bot_manager
from ..logger_config import get_logger
from .auth import get_current_user_from_token

logger = get_logger("control_api")

def get_colombia_time():
    return datetime.utcnow() - timedelta(hours=5)

router = APIRouter(prefix="/bot", tags=["Control"])


class ManualSellRequest(BaseModel):
    pair: str

class ManualBuyRequest(BaseModel):
    pair: str
@router.post("/{user_id}/manual_buy")
async def manual_buy(user_id: int, body: ManualBuyRequest, request: Request, db: Session = Depends(get_db)):
    """Compra manual de una moneda. Solo si no hay posición abierta en esa moneda."""
    current = get_current_user_from_token(request)
    if current["role"] != "admin" and int(current["sub"]) != user_id:
        raise HTTPException(status_code=403, detail="Solo puedes controlar tu propio bot")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if not user.coinex_api_key or not user.coinex_secret:
        raise HTTPException(status_code=400, detail="API keys de CoinEx no configuradas")

    pair = body.pair.strip()
    if "/" not in pair:
        raise HTTPException(status_code=400, detail="Par inválido. Formato esperado: BTC/USDT")

    quote_currency = pair.split("/")[1]
    test_mode = user.test_mode if user.test_mode is not None else True

    # Calcular posiciones abiertas
    trades = db.query(Trade).filter(Trade.user_id == user_id).order_by(Trade.timestamp.asc()).all()
    positions = defaultdict(lambda: {"amount": 0.0, "total_cost": 0.0})
    for t in trades:
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

    position = positions.get(pair)
    if position and position["amount"] > 0.0001:
        raise HTTPException(status_code=400, detail=f"Ya tienes una posición abierta en {pair}. Debes vender antes de comprar de nuevo.")

    # Obtener saldo USDT disponible
    try:
        exchange = ccxt.coinex({
            "apiKey": user.coinex_api_key,
            "secret": user.coinex_secret,
            "enableRateLimit": True,
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al conectar con CoinEx: {str(e)[:200]}")

    usdt_free = 0.0
    if not test_mode:
        try:
            balance = exchange.fetch_balance()
            if quote_currency in balance and isinstance(balance[quote_currency], dict):
                usdt_free = float(balance[quote_currency].get("free", 0) or 0)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error al obtener balance: {str(e)[:200]}")
    else:
        # En test mode, simular saldo
        usdt_free = 1000.0

    if usdt_free < 5.0:
        raise HTTPException(status_code=400, detail=f"Saldo insuficiente en {quote_currency} para comprar (mínimo 5 USDT)")

    # Obtener precio actual
    try:
        ticker = exchange.fetch_ticker(pair)
        current_price = float(ticker.get("last", 0))
        if current_price <= 0:
            raise HTTPException(status_code=500, detail=f"No se pudo obtener precio actual de {pair}")
    except ccxt.BaseError as e:
        raise HTTPException(status_code=500, detail=f"Error al obtener precio de {pair}: {str(e)[:200]}")

    # Calcular monto a invertir según perfil de riesgo
    invest_pct = user.invest_percentage or 25.0
    amount_usdt = usdt_free * (invest_pct / 100.0)
    if amount_usdt > usdt_free:
        amount_usdt = usdt_free
    if amount_usdt < 1.0:
        raise HTTPException(status_code=400, detail=f"Monto insuficiente para comprar (mínimo 1 USDT)")

    amount = amount_usdt / current_price

    # Ejecutar orden
    order_id = None
    simulated = test_mode

    if test_mode:
        order_id = f"manual_buy_sim_{pair}_{int(time.time() * 1000)}"
        logger.info(
            "[COMPRA MANUAL SIMULADA] Usuario %s compró %s: %.8f @ %.6f | Monto: %.4f USDT",
            user.username, pair, amount, current_price, amount_usdt
        )
    else:
        try:
            market = exchange.market(pair)
            precision = market.get("precision", {})
            amount_precision = precision.get("amount")
            if amount_precision is not None:
                if isinstance(amount_precision, (int, float)) and amount_precision >= 1:
                    amount = round(amount, 0)
                elif isinstance(amount_precision, (int, float)):
                    s = f"{amount_precision:.10f}".rstrip("0")
                    decimals = len(s.split(".")[-1]) if "." in s else 0
                    amount = round(amount, decimals)

            order = exchange.create_limit_order(pair, "buy", amount, current_price)
            order_id = order.get("id", f"manual_buy_{int(time.time() * 1000)}")
            filled = order.get("filled", amount)
            exec_price = order.get("average") or order.get("price") or current_price
            amount = float(filled) if filled else amount
            current_price = float(exec_price) if exec_price else current_price
            logger.info(
                "[COMPRA MANUAL REAL] Usuario %s compró %s: %.8f @ %.6f | Monto: %.4f USDT | Order ID: %s",
                user.username, pair, amount, current_price, amount_usdt, order_id
            )
        except ccxt.InsufficientFunds as e:
            raise HTTPException(status_code=400, detail=f"Saldo insuficiente: {str(e)[:200]}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error al ejecutar compra: {str(e)[:200]}")

    # Guardar trade en DB
    new_trade = Trade(
        user_id=user_id,
        pair=pair,
        side="buy",
        amount=amount,
        price=current_price,
        order_id=f"manual_buy_{order_id}",
        simulated=simulated,
        profit=0.0,
        max_price_reached=current_price
    )
    db.add(new_trade)
    db.commit()

    # Log para el bot del usuario
    from backend.logger_config import get_user_bot_logger
    user_log = get_user_bot_logger(user_id, user.username)
    user_log.info(
        "🟢 COMPRA MANUAL ejecutada: %s | Cantidad: %.8f | Precio: %.6f | Monto: %.4f USDT | Simulada: %s | OrderID: %s",
        pair, amount, current_price, amount_usdt, simulated, order_id
    )

    # Notificación Telegram
    try:
        import requests as req
        token = user.telegram_bot_token
        chat_id = user.telegram_chat_id
        if token and chat_id:
            text = (
                f"🟢 <b>COMPRA MANUAL</b>\n"
                f"{'[SIMULADA] ' if simulated else ''}Par: {pair}\n"
                f"Cantidad: {amount:.8f}\n"
                f"Precio de compra: {current_price:.6f}\n"
                f"Monto invertido: {amount_usdt:.4f} USDT\n"
                f"Razón: Compra manual del usuario"
            )
            req.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
                timeout=10
            )
    except Exception as e:
        logger.warning("Error al enviar Telegram de compra manual: %s", str(e)[:100])

    # Actualizar balance virtual si está en test mode y el bot está corriendo
    from bot.bot_manager import _virtual_balances, _update_virtual_balance
    if test_mode and user_id in _virtual_balances:
        _update_virtual_balance(user_id, "buy", pair, amount, current_price)

    return {
        "message": f"Compra manual ejecutada exitosamente",
        "pair": pair,
        "amount": amount,
        "price": current_price,
        "amount_usdt": round(amount_usdt, 4),
        "simulated": simulated,
        "order_id": order_id
    }

@router.post("/{user_id}/start")
async def start_user_bot(user_id: int, request: Request, db: Session = Depends(get_db)):
    """Admin: inicia cualquier bot. User: solo su bot."""
    current = get_current_user_from_token(request)
    if current["role"] != "admin" and int(current["sub"]) != user_id:
        raise HTTPException(status_code=403, detail="Solo puedes controlar tu propio bot")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    started = await bot_manager.start_bot(user_id)
    if not started:
        return {"message": f"Bot for user {user.username} is already running"}
    
    user.is_active = True
    db.commit()
    return {"message": f"Bot for user {user.username} started"}

@router.post("/{user_id}/stop")
async def stop_user_bot(user_id: int, request: Request, db: Session = Depends(get_db)):
    """Admin: detiene cualquier bot. User: solo su bot."""
    current = get_current_user_from_token(request)
    if current["role"] != "admin" and int(current["sub"]) != user_id:
        raise HTTPException(status_code=403, detail="Solo puedes controlar tu propio bot")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    stopped = await bot_manager.stop_bot(user_id)
    
    if user.is_active or stopped:
        user.is_active = False
        db.commit()
        logger.info(f"Estado de usuario {user.username} sincronizado a INACTIVO en DB")
    
    if not stopped:
        return {"message": f"Bot for user {user.username} was not in memory, but DB state is now synchronized to STOPPED"}
        
    return {"message": f"Bot for user {user.username} stopped successfully"}

@router.get("/status")
def get_bots_status():
    return {"active_bots_count": len(bot_manager.active_bots), "active_user_ids": list(bot_manager.active_bots.keys())}


@router.post("/{user_id}/manual_sell")
async def manual_sell(user_id: int, body: ManualSellRequest, request: Request, db: Session = Depends(get_db)):
    """Venta manual de una posición abierta. Se registra como venta manual en logs y estadísticas."""
    current = get_current_user_from_token(request)
    if current["role"] != "admin" and int(current["sub"]) != user_id:
        raise HTTPException(status_code=403, detail="Solo puedes controlar tu propio bot")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if not user.coinex_api_key or not user.coinex_secret:
        raise HTTPException(status_code=400, detail="API keys de CoinEx no configuradas")

    pair = body.pair.strip()
    if "/" not in pair:
        raise HTTPException(status_code=400, detail="Par inválido. Formato esperado: BTC/USDT")

    base_currency = pair.split("/")[0]
    test_mode = user.test_mode if user.test_mode is not None else True

    # Calcular posición abierta desde el historial de trades en BD
    trades = db.query(Trade).filter(Trade.user_id == user_id).order_by(Trade.timestamp.asc()).all()
    positions = defaultdict(lambda: {"amount": 0.0, "total_cost": 0.0})
    for t in trades:
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

    position = positions.get(pair)
    if not position or position["amount"] < 0.0001:
        raise HTTPException(status_code=400, detail=f"No tienes posición abierta en {pair}")

    db_amount = position["amount"]
    avg_entry_price = position["total_cost"] / db_amount if db_amount > 0 else 0.0

    # Crear exchange con credenciales del usuario
    try:
        exchange = ccxt.coinex({
            "apiKey": user.coinex_api_key,
            "secret": user.coinex_secret,
            "enableRateLimit": True,
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al conectar con CoinEx: {str(e)[:200]}")

    # Obtener precio actual
    try:
        ticker = exchange.fetch_ticker(pair)
        current_price = float(ticker.get("last", 0))
        if current_price <= 0:
            raise HTTPException(status_code=500, detail=f"No se pudo obtener precio actual de {pair}")
    except ccxt.BaseError as e:
        raise HTTPException(status_code=500, detail=f"Error al obtener precio de {pair}: {str(e)[:200]}")

    # Obtener balance real del exchange para saber cuánto hay disponible
    sell_amount = db_amount
    if not test_mode:
        try:
            balance = exchange.fetch_balance()
            real_free = 0.0
            if base_currency in balance and isinstance(balance[base_currency], dict):
                real_free = float(balance[base_currency].get("free", 0) or 0)
            if real_free < 0.0001:
                raise HTTPException(status_code=400, detail=f"No tienes saldo disponible de {base_currency} en CoinEx")
            sell_amount = min(db_amount, real_free)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error al obtener balance: {str(e)[:200]}")

    # Calcular profit
    invested_value = sell_amount * avg_entry_price
    current_value = sell_amount * current_price
    profit = current_value - invested_value

    # Ejecutar orden
    order_id = None
    simulated = test_mode

    if test_mode:
        order_id = f"manual_sell_sim_{pair}_{int(time.time() * 1000)}"
        logger.info(
            "[VENTA MANUAL SIMULADA] Usuario %s vendió %s: %.8f @ %.6f | Profit: %.4f USDT",
            user.username, pair, sell_amount, current_price, profit
        )
    else:
        try:
            # Redondear según precisión del mercado
            market = exchange.market(pair)
            precision = market.get("precision", {})
            amount_precision = precision.get("amount")
            if amount_precision is not None:
                if isinstance(amount_precision, (int, float)) and amount_precision >= 1:
                    sell_amount = round(sell_amount, 0)
                elif isinstance(amount_precision, (int, float)):
                    s = f"{amount_precision:.10f}".rstrip("0")
                    decimals = len(s.split(".")[-1]) if "." in s else 0
                    sell_amount = round(sell_amount, decimals)

            order = exchange.create_limit_order(pair, "sell", sell_amount, current_price)
            order_id = order.get("id", f"manual_sell_{int(time.time() * 1000)}")
            filled = order.get("filled", sell_amount)
            exec_price = order.get("average") or order.get("price") or current_price
            sell_amount = float(filled) if filled else sell_amount
            current_price = float(exec_price) if exec_price else current_price
            profit = (sell_amount * current_price) - (sell_amount * avg_entry_price)
            logger.info(
                "[VENTA MANUAL REAL] Usuario %s vendió %s: %.8f @ %.6f | Profit: %.4f USDT | Order ID: %s",
                user.username, pair, sell_amount, current_price, profit, order_id
            )
        except ccxt.InsufficientFunds as e:
            raise HTTPException(status_code=400, detail=f"Saldo insuficiente: {str(e)[:200]}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error al ejecutar venta: {str(e)[:200]}")

    # Guardar trade en DB
    new_trade = Trade(
        user_id=user_id,
        pair=pair,
        side="sell",
        amount=sell_amount,
        price=current_price,
        order_id=f"manual_sell_{order_id}",
        simulated=simulated,
        profit=profit,
        max_price_reached=0.0
    )
    db.add(new_trade)
    db.commit()

    # Log para el bot del usuario
    from backend.logger_config import get_user_bot_logger
    user_log = get_user_bot_logger(user_id, user.username)
    user_log.info(
        "🔴 VENTA MANUAL ejecutada: %s | Cantidad: %.8f | Precio: %.6f | Profit: %.4f USDT | Simulada: %s | OrderID: %s",
        pair, sell_amount, current_price, profit, simulated, order_id
    )

    # Notificación Telegram
    try:
        import requests as req
        token = user.telegram_bot_token
        chat_id = user.telegram_chat_id
        if token and chat_id:
            text = (
                f"🔴 <b>VENTA MANUAL</b>\n"
                f"{'[SIMULADA] ' if simulated else ''}Par: {pair}\n"
                f"Cantidad: {sell_amount:.8f}\n"
                f"Precio de venta: {current_price:.6f}\n"
                f"Precio promedio compra: {avg_entry_price:.6f}\n"
                f"Profit: <b>{'🟢' if profit >= 0 else '🔴'} {profit:.4f} USDT</b>\n"
                f"Razón: Venta manual del usuario"
            )
            req.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
                timeout=10
            )
    except Exception as e:
        logger.warning("Error al enviar Telegram de venta manual: %s", str(e)[:100])

    # Actualizar balance virtual si está en test mode y el bot está corriendo
    from bot.bot_manager import _virtual_balances, _update_virtual_balance
    if test_mode and user_id in _virtual_balances:
        _update_virtual_balance(user_id, "sell", pair, sell_amount, current_price)

    return {
        "message": f"Venta manual ejecutada exitosamente",
        "pair": pair,
        "amount": sell_amount,
        "price": current_price,
        "avg_entry_price": avg_entry_price,
        "profit": round(profit, 4),
        "simulated": simulated,
        "order_id": order_id
    }
