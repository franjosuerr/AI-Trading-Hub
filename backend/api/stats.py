from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import func, case, extract
from ..database import get_db
from ..models.models import Trade, User
from ..schemas import TradeResponse
from .auth import get_current_user_from_token
from typing import List
from datetime import datetime, timedelta
from collections import defaultdict
import ccxt

def get_colombia_time():
    return datetime.utcnow() - timedelta(hours=5)

router = APIRouter(prefix="/stats", tags=["Statistics"])


@router.get("/{user_id}/balance")
def get_user_balance(user_id: int, request: Request, db: Session = Depends(get_db)):
    """Obtiene el saldo actual de CoinEx del usuario."""
    current = get_current_user_from_token(request)
    if current["role"] != "admin" and int(current["sub"]) != user_id:
        raise HTTPException(status_code=403, detail="No tienes acceso")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if not user.coinex_api_key or not user.coinex_secret:
        return {"balances": [], "total_usdt": 0, "error": "API keys no configuradas"}

    try:
        exchange = ccxt.coinex({
            "apiKey": user.coinex_api_key,
            "secret": user.coinex_secret,
            "enableRateLimit": True
        })
        raw = exchange.fetch_balance()
        balances = []
        total_usdt = 0

        for currency, data in raw.items():
            if currency in ("info", "timestamp", "datetime", "free", "used", "total"):
                continue
            if not isinstance(data, dict):
                continue
            free = float(data.get("free", 0) or 0)
            used = float(data.get("used", 0) or 0)
            total = float(data.get("total", 0) or 0)
            if total > 0 or free > 0:
                # Estimar valor en USDT
                usdt_value = 0
                if currency == "USDT":
                    usdt_value = total
                else:
                    try:
                        ticker = exchange.fetch_ticker(f"{currency}/USDT")
                        usdt_value = total * (ticker.get("last", 0) or 0)
                    except Exception:
                        usdt_value = 0

                balances.append({
                    "currency": currency,
                    "free": round(free, 8),
                    "used": round(used, 8),
                    "total": round(total, 8),
                    "usdt_value": round(usdt_value, 2)
                })
                total_usdt += usdt_value

        # Ordenar por valor USDT descendente
        balances.sort(key=lambda x: x["usdt_value"], reverse=True)
        return {"balances": balances, "total_usdt": round(total_usdt, 2)}
    except ccxt.AuthenticationError:
        return {"balances": [], "total_usdt": 0, "error": "API keys inválidas"}
    except Exception as e:
        return {"balances": [], "total_usdt": 0, "error": str(e)[:200]}



@router.get("/summary")
def get_global_summary(db: Session = Depends(get_db)):
    total_users = db.query(User).count()
    active_bots = db.query(User).filter(User.is_active == True).count()
    total_profit = db.query(func.sum(Trade.profit)).scalar() or 0.0
    return {
        "total_users": total_users,
        "active_bots": active_bots,
        "total_profit": total_profit
    }


@router.get("/{user_id}/trades", response_model=List[TradeResponse])
def get_user_trades(user_id: int, request: Request, db: Session = Depends(get_db)):
    current = get_current_user_from_token(request)
    if current["role"] != "admin" and int(current["sub"]) != user_id:
        raise HTTPException(status_code=403, detail="No tienes acceso")
    return db.query(Trade).filter(Trade.user_id == user_id).order_by(Trade.timestamp.desc()).all()


@router.get("/{user_id}/monthly")
def get_monthly_stats(user_id: int, request: Request, month: str = None, db: Session = Depends(get_db)):
    """
    Estadísticas mensuales de un usuario.
    month: formato YYYY-MM (default: mes actual)
    """
    current = get_current_user_from_token(request)
    if current["role"] != "admin" and int(current["sub"]) != user_id:
        raise HTTPException(status_code=403, detail="No tienes acceso a estas estadísticas")

    # Determinar rango de fechas
    if month:
        try:
            year, mon = map(int, month.split("-"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Formato de mes inválido. Usa YYYY-MM")
    else:
        now = get_colombia_time()
        year, mon = now.year, now.month

    # Inicio y fin del mes
    start_date = datetime(year, mon, 1)
    if mon == 12:
        end_date = datetime(year + 1, 1, 1)
    else:
        end_date = datetime(year, mon + 1, 1)

    # Obtener trades del mes
    trades = db.query(Trade).filter(
        Trade.user_id == user_id,
        Trade.timestamp >= start_date,
        Trade.timestamp < end_date
    ).order_by(Trade.timestamp.asc()).all()

    # ─── Métricas resumen ───
    total_trades = len(trades)
    total_profit = sum(t.profit for t in trades)
    winning_trades = sum(1 for t in trades if t.profit > 0)
    losing_trades = sum(1 for t in trades if t.profit < 0)
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
    avg_profit = total_profit / total_trades if total_trades > 0 else 0
    best_trade = max((t.profit for t in trades), default=0)
    worst_trade = min((t.profit for t in trades), default=0)
    total_buys = sum(1 for t in trades if t.side == "buy")
    total_sells = sum(1 for t in trades if t.side == "sell")
    total_volume = sum(t.amount * t.price for t in trades)

    # ─── Profit acumulado por día ───
    daily_profit = defaultdict(float)
    for t in trades:
        day = t.timestamp.strftime("%Y-%m-%d")
        daily_profit[day] += t.profit

    # Crear serie acumulada
    cumulative = 0
    profit_timeline = []
    for day in sorted(daily_profit.keys()):
        cumulative += daily_profit[day]
        profit_timeline.append({
            "date": day,
            "daily": round(daily_profit[day], 4),
            "cumulative": round(cumulative, 4)
        })

    # ─── Trades por par ───
    pair_stats = defaultdict(lambda: {"buys": 0, "sells": 0, "profit": 0, "count": 0})
    for t in trades:
        pair_stats[t.pair]["count"] += 1
        pair_stats[t.pair]["profit"] += t.profit
        if t.side == "buy":
            pair_stats[t.pair]["buys"] += 1
        else:
            pair_stats[t.pair]["sells"] += 1

    trades_by_pair = [
        {"pair": pair, "count": d["count"], "buys": d["buys"], "sells": d["sells"], "profit": round(d["profit"], 4)}
        for pair, d in pair_stats.items()
    ]

    # ─── Últimos trades ───
    recent_trades = [
        {
            "id": t.id,
            "pair": t.pair,
            "side": t.side,
            "amount": t.amount,
            "price": t.price,
            "profit": t.profit,
            "simulated": t.simulated,
            "timestamp": t.timestamp.isoformat()
        }
        for t in trades[-20:]  # Últimos 20
    ]

    return {
        "user_id": user_id,
        "month": f"{year}-{mon:02d}",
        "summary": {
            "total_trades": total_trades,
            "total_profit": round(total_profit, 4),
            "win_rate": round(win_rate, 1),
            "avg_profit": round(avg_profit, 4),
            "best_trade": round(best_trade, 4),
            "worst_trade": round(worst_trade, 4),
            "total_buys": total_buys,
            "total_sells": total_sells,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "total_volume": round(total_volume, 2),
        },
        "profit_timeline": profit_timeline,
        "trades_by_pair": trades_by_pair,
        "buy_sell_ratio": [
            {"name": "Compras", "value": total_buys},
            {"name": "Ventas", "value": total_sells}
        ],
        "recent_trades": recent_trades
    }
