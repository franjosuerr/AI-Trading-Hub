# email_notifier.py
# Envío de notificaciones por email cuando se ejecuta un trade exitoso.
# Si las variables SMTP no están configuradas, no envía y no lanza excepciones.

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

from backend.logger_config import get_logger

logger = get_logger("email_notifier")

# Configuración SMTP desde variables de entorno
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "")


def _is_configured() -> bool:
    """Verifica si las variables SMTP están configuradas."""
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASSWORD and EMAIL_FROM)


def _build_trade_html(
    pair: str,
    side: str,
    amount: float,
    price: float,
    order_id: str,
    simulated: bool,
    indicators: dict,
    balance_after: str,
    confidence: float = 0.0,
    reason: str = "",
) -> str:
    """Genera el HTML del email con datos del trade e indicadores de mercado."""

    is_buy = side.lower() == "buy"
    side_label = "COMPRA" if is_buy else "VENTA"
    side_emoji = "🟢" if is_buy else "🔴"
    side_color = "#10b981" if is_buy else "#ef4444"
    sim_badge = '<span style="background:#f59e0b;color:#000;padding:2px 8px;border-radius:4px;font-size:12px;">SIMULADA</span>' if simulated else ""
    total_cost = amount * price if price else 0

    # Indicadores con formato seguro
    def fmt(val, decimals=2):
        if val is None:
            return "N/A"
        try:
            return f"{float(val):,.{decimals}f}"
        except (ValueError, TypeError):
            return "N/A"

    rsi = indicators.get("rsi")
    rsi_color = "#ef4444" if rsi and rsi > 70 else "#10b981" if rsi and rsi < 30 else "#6b7280"

    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="margin:0;padding:0;background:#0f172a;font-family:'Segoe UI',Arial,sans-serif;">
        <div style="max-width:600px;margin:0 auto;padding:20px;">
            <!-- Header -->
            <div style="background:linear-gradient(135deg,{'#064e3b' if is_buy else '#7f1d1d'},{'#065f46' if is_buy else '#991b1b'});
                        border-radius:12px 12px 0 0;padding:24px;text-align:center;">
                <h1 style="margin:0;color:#fff;font-size:24px;">
                    {side_emoji} Orden de {side_label} Ejecutada
                </h1>
                <p style="margin:8px 0 0;color:rgba(255,255,255,0.7);font-size:14px;">
                    {timestamp} {sim_badge}
                </p>
            </div>

            <!-- Trade Details -->
            <div style="background:#1e293b;padding:24px;border-left:1px solid #334155;border-right:1px solid #334155;">
                <h2 style="margin:0 0 16px;color:#e2e8f0;font-size:18px;border-bottom:1px solid #334155;padding-bottom:8px;">
                    📊 Detalles del Trade
                </h2>
                <table style="width:100%;border-collapse:collapse;">
                    <tr>
                        <td style="padding:8px 0;color:#94a3b8;font-size:14px;">Par</td>
                        <td style="padding:8px 0;color:#f1f5f9;font-size:14px;text-align:right;font-weight:bold;">{pair}</td>
                    </tr>
                    <tr>
                        <td style="padding:8px 0;color:#94a3b8;font-size:14px;">Tipo</td>
                        <td style="padding:8px 0;color:{side_color};font-size:14px;text-align:right;font-weight:bold;">{side_label}</td>
                    </tr>
                    <tr>
                        <td style="padding:8px 0;color:#94a3b8;font-size:14px;">Cantidad</td>
                        <td style="padding:8px 0;color:#f1f5f9;font-size:14px;text-align:right;">{fmt(amount, 8)}</td>
                    </tr>
                    <tr>
                        <td style="padding:8px 0;color:#94a3b8;font-size:14px;">Precio</td>
                        <td style="padding:8px 0;color:#f1f5f9;font-size:14px;text-align:right;">${fmt(price)}</td>
                    </tr>
                    <tr style="background:#0f172a;border-radius:8px;">
                        <td style="padding:12px 8px;color:#94a3b8;font-size:14px;font-weight:bold;">Costo Total</td>
                        <td style="padding:12px 8px;color:#fbbf24;font-size:16px;text-align:right;font-weight:bold;">${fmt(total_cost)}</td>
                    </tr>
                    <tr>
                        <td style="padding:8px 0;color:#94a3b8;font-size:14px;">ID Orden</td>
                        <td style="padding:8px 0;color:#64748b;font-size:12px;text-align:right;">{order_id}</td>
                    </tr>
                    <tr>
                        <td style="padding:8px 0;color:#94a3b8;font-size:14px;">Confianza IA</td>
                        <td style="padding:8px 0;color:#818cf8;font-size:14px;text-align:right;">{fmt(confidence * 100, 1)}%</td>
                    </tr>
                </table>
            </div>

            <!-- Market Indicators -->
            <div style="background:#1e293b;padding:24px;border-left:1px solid #334155;border-right:1px solid #334155;">
                <h2 style="margin:0 0 16px;color:#e2e8f0;font-size:18px;border-bottom:1px solid #334155;padding-bottom:8px;">
                    📈 Estado del Mercado
                </h2>
                <table style="width:100%;border-collapse:collapse;">
                    <tr>
                        <td style="padding:8px 0;color:#94a3b8;font-size:14px;">RSI</td>
                        <td style="padding:8px 0;color:{rsi_color};font-size:14px;text-align:right;font-weight:bold;">{fmt(rsi, 1)}</td>
                    </tr>
                    <tr>
                        <td style="padding:8px 0;color:#94a3b8;font-size:14px;">MACD Línea</td>
                        <td style="padding:8px 0;color:#f1f5f9;font-size:14px;text-align:right;">{fmt(indicators.get('macd_line'), 4)}</td>
                    </tr>
                    <tr>
                        <td style="padding:8px 0;color:#94a3b8;font-size:14px;">MACD Signal</td>
                        <td style="padding:8px 0;color:#f1f5f9;font-size:14px;text-align:right;">{fmt(indicators.get('macd_signal'), 4)}</td>
                    </tr>
                    <tr>
                        <td style="padding:8px 0;color:#94a3b8;font-size:14px;">MACD Histograma</td>
                        <td style="padding:8px 0;color:#f1f5f9;font-size:14px;text-align:right;">{fmt(indicators.get('macd_histogram'), 4)}</td>
                    </tr>
                    <tr>
                        <td style="padding:8px 0;color:#94a3b8;font-size:14px;">SMA 50</td>
                        <td style="padding:8px 0;color:#f1f5f9;font-size:14px;text-align:right;">${fmt(indicators.get('sma50'))}</td>
                    </tr>
                    <tr>
                        <td style="padding:8px 0;color:#94a3b8;font-size:14px;">SMA 200</td>
                        <td style="padding:8px 0;color:#f1f5f9;font-size:14px;text-align:right;">${fmt(indicators.get('sma200'))}</td>
                    </tr>
                    <tr>
                        <td style="padding:8px 0;color:#94a3b8;font-size:14px;">Bollinger Superior</td>
                        <td style="padding:8px 0;color:#f1f5f9;font-size:14px;text-align:right;">${fmt(indicators.get('bb_upper'))}</td>
                    </tr>
                    <tr>
                        <td style="padding:8px 0;color:#94a3b8;font-size:14px;">Bollinger Inferior</td>
                        <td style="padding:8px 0;color:#f1f5f9;font-size:14px;text-align:right;">${fmt(indicators.get('bb_lower'))}</td>
                    </tr>
                    <tr>
                        <td style="padding:8px 0;color:#94a3b8;font-size:14px;">Volumen</td>
                        <td style="padding:8px 0;color:#f1f5f9;font-size:14px;text-align:right;">{fmt(indicators.get('volume'))}</td>
                    </tr>
                    <tr>
                        <td style="padding:8px 0;color:#94a3b8;font-size:14px;">Volumen Promedio</td>
                        <td style="padding:8px 0;color:#f1f5f9;font-size:14px;text-align:right;">{fmt(indicators.get('volume_avg'))}</td>
                    </tr>
                </table>
            </div>

            <!-- AI Reason -->
            <div style="background:#1e293b;padding:24px;border-left:1px solid #334155;border-right:1px solid #334155;">
                <h2 style="margin:0 0 12px;color:#e2e8f0;font-size:18px;border-bottom:1px solid #334155;padding-bottom:8px;">
                    🤖 Razón de la IA
                </h2>
                <p style="margin:0;color:#cbd5e1;font-size:14px;line-height:1.6;font-style:italic;">
                    "{reason[:500] if reason else 'Sin razón proporcionada'}"
                </p>
            </div>

            <!-- Balance -->
            <div style="background:#1e293b;padding:24px;border-left:1px solid #334155;border-right:1px solid #334155;
                        border-radius:0 0 12px 12px;border-bottom:1px solid #334155;">
                <h2 style="margin:0 0 8px;color:#e2e8f0;font-size:18px;">
                    💰 Balance después del trade
                </h2>
                <p style="margin:0;color:#fbbf24;font-size:14px;">{balance_after or 'No disponible'}</p>
            </div>

            <!-- Footer -->
            <div style="text-align:center;padding:16px;color:#475569;font-size:12px;">
                AI Trading Bot — Notificación automática
            </div>
        </div>
    </body>
    </html>
    """
    return html


def send_trade_email(
    to_email: str,
    pair: str,
    side: str,
    amount: float,
    price: float,
    order_id: str,
    simulated: bool,
    indicators: dict,
    balance_after: str,
    confidence: float = 0.0,
    reason: str = "",
) -> bool:
    """
    Envía un email con los detalles del trade ejecutado y estadísticas del mercado.
    Retorna True si se envió correctamente, False en cualquier otro caso.
    NUNCA lanza excepciones.
    """
    try:
        if not _is_configured():
            logger.debug("Email: SMTP no configurado. No se envía notificación.")
            return False

        if not to_email:
            logger.debug("Email: usuario sin email registrado. No se envía notificación.")
            return False

        side_label = "COMPRA" if side.lower() == "buy" else "VENTA"
        subject = f"{'🟢' if side.lower() == 'buy' else '🔴'} {side_label} ejecutada — {pair} | AI Trading Bot"

        html_body = _build_trade_html(
            pair=pair,
            side=side,
            amount=amount,
            price=price,
            order_id=order_id,
            simulated=simulated,
            indicators=indicators,
            balance_after=balance_after,
            confidence=confidence,
            reason=reason,
        )

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = EMAIL_FROM
        msg["To"] = to_email
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(EMAIL_FROM, [to_email], msg.as_string())

        logger.info("Email: notificación de %s %s enviada a %s", side_label, pair, to_email)
        return True

    except smtplib.SMTPAuthenticationError:
        logger.warning("Email: error de autenticación SMTP. Revisa SMTP_USER y SMTP_PASSWORD.")
        return False
    except smtplib.SMTPException as e:
        logger.warning("Email: error SMTP al enviar: %s", str(e)[:150])
        return False
    except OSError as e:
        logger.warning("Email: error de red/conexión: %s", str(e)[:150])
        return False
    except Exception as e:
        logger.warning("Email: error inesperado: %s", str(e)[:150])
        return False
