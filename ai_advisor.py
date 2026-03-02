# ai_advisor.py
# Construcción del prompt y llamada a la IA (OpenAI, Groq, Google Gemini u Ollama local).

import json
from typing import Optional

from config import (
    AI_PROVIDER,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    GROQ_API_KEY,
    GROQ_MODEL,
    GOOGLE_API_KEY,
    GEMINI_MODEL,
    OLLAMA_HOST,
    OLLAMA_MODEL,
)
from logger_config import get_logger
from utils import format_candles_for_prompt, validate_ai_signal

logger = get_logger("ai_advisor")

# Cliente OpenAI (compatible con OpenAI, Groq y Ollama)
try:
    from openai import OpenAI
    from openai import RateLimitError as OpenAIRateLimitError
    from openai import APIError as OpenAIAPIError
    _HAS_OPENAI = True
except ImportError:
    _HAS_OPENAI = False

# Google Gemini (opcional)
def _get_gemini_client():
    try:
        import google.generativeai as genai
        return genai
    except ImportError:
        return None


def build_prompt(
    pair: str,
    timeframe: str,
    candles_text: str,
    indicators: dict,
    prompt_candles: int,
    context_summary: Optional[str] = None,
    current_price: Optional[float] = None,
    portfolio_context: Optional[dict] = None,
    stop_loss_percent: Optional[float] = None,
    num_pairs: int = 1,
) -> str:
    """
    Construye el prompt para la IA con par, timeframe, últimas velas OHLCV,
    resumen de contexto (tendencia, máximos/mínimos), indicadores, precio actual,
    portafolio completo (balance, posiciones, costos) y stop-loss.
    La IA decide señal + monto como un trader profesional.
    """
    ind_lines = []
    for k, v in (indicators or {}).items():
        if v is not None:
            ind_lines.append(f"  {k}: {v}")
    indicators_block = "\n".join(ind_lines) if ind_lines else "  (no disponibles)"

    context_block = ""
    if context_summary and context_summary.strip():
        context_block = f"\n**Contexto (resumen de más velas pasadas):**\n{context_summary.strip()}\n"

    price_block = ""
    if current_price is not None:
        price_block = f"\n**Precio actual (ticker):** {current_price}\n"

    # --- Construir bloque de portafolio (como un trader profesional) ---
    base_currency = pair.split("/")[0] if "/" in pair else pair
    quote_currency = pair.split("/")[1] if "/" in pair else "USDT"

    portfolio_block = ""
    balance_instruction = ""
    holdings = 0.0
    free_quote = 0.0
    avg_entry = 0.0
    pnl_pct = 0.0

    if portfolio_context:
        free_quote = portfolio_context.get("free_quote", 0.0)
        holdings = portfolio_context.get("holdings", 0.0)
        avg_entry = portfolio_context.get("avg_entry_price", 0.0)
        invested = portfolio_context.get("invested_value", 0.0)
        current_val = portfolio_context.get("current_value", 0.0)
        pnl_usdt = portfolio_context.get("pnl_usdt", 0.0)
        pnl_pct = portfolio_context.get("pnl_pct", 0.0)
        total_buys = portfolio_context.get("total_trades_buy", 0)
        total_sells = portfolio_context.get("total_trades_sell", 0)

        portfolio_lines = [
            f"\n**Tu portafolio actual (cuenta real):**",
            f"  - {quote_currency} disponible: {free_quote:.4f} {quote_currency}",
            f"  - Posición en {base_currency}: {holdings:.8f} {base_currency}",
        ]
        if holdings > 0 and avg_entry > 0:
            portfolio_lines.extend([
                f"  - Precio promedio de compra: {avg_entry:.6f} {quote_currency}",
                f"  - Valor invertido: {invested:.4f} {quote_currency}",
                f"  - Valor actual de la posición: {current_val:.4f} {quote_currency}",
                f"  - Ganancia/Pérdida: {pnl_usdt:+.4f} {quote_currency} ({pnl_pct:+.2f}%)",
            ])
        portfolio_lines.append(f"  - Historial: {total_buys} compras, {total_sells} ventas realizadas")
        portfolio_lines.append(f"  - Pares que monitoreo: {num_pairs} pares (distribuye el capital inteligentemente)")
        portfolio_block = "\n".join(portfolio_lines) + "\n"

        # Instrucciones inteligentes según estado del portafolio
        invested_pct_of_balance = 0.0
        if free_quote > 0 and invested > 0:
            invested_pct_of_balance = (invested / (free_quote + invested)) * 100

        if holdings <= 0 or holdings < 0.000001:
            balance_instruction = (
                f"\n**REGLA DE SALDO:** No tienes {base_currency} (posición vacía). "
                f"NO puedes vender, así que NO emitas señal 'sell'. "
                f"Si tienes {quote_currency} disponible y la oportunidad es buena, "
                f"busca oportunidades de COMPRA.\n"
            )
        elif holdings > 0 and invested_pct_of_balance > 50:
            balance_instruction = (
                f"\n**⚠️ ALERTA - POSICIÓN GRANDE:** Ya tienes {holdings:.8f} {base_currency} "
                f"(~{invested:.2f} {quote_currency}, {invested_pct_of_balance:.1f}% de tu capital total en este par). "
                f"Tu {quote_currency} libre es solo {free_quote:.4f}. "
                f"NO compres más a menos que haya una señal EXTREMADAMENTE fuerte (confianza > 0.90). "
                f"Considera MANTENER o VENDER parcialmente si hay ganancias. "
                f"Prioriza proteger el capital existente.\n"
            )
        elif holdings > 0 and pnl_pct < -(stop_loss_percent or 2.0):
            balance_instruction = (
                f"\n**ALERTA DE RIESGO:** Tu posición en {base_currency} está en pérdida ({pnl_pct:+.2f}%). "
                f"Evalúa seriamente si conviene vender para cortar pérdidas (stop-loss) "
                f"o si los indicadores muestran recuperación.\n"
            )
        elif holdings > 0:
            balance_instruction = (
                f"\n**NOTA:** Ya tienes posición abierta en {base_currency} ({holdings:.8f}, "
                f"invertido ~{invested:.2f} {quote_currency}, P&L: {pnl_pct:+.2f}%). "
                f"Sé conservador: no acumules comprando en cada ciclo. "
                f"Compra adicional SOLO si los indicadores muestran una oportunidad clara de DCA (Dollar Cost Averaging) "
                f"con confianza alta. Considera MANTENER si no hay cambios claros.\n"
            )
    else:
        portfolio_block = "\n**Portafolio:** No disponible (primera ejecución).\n"

    risk_block = ""
    if stop_loss_percent is not None and stop_loss_percent > 0:
        risk_block = f"\nStop-loss configurado al {stop_loss_percent}%; sé conservador con el riesgo a la baja.\n"

    return f"""Analiza el par {pair} (timeframe: {timeframe}) con los siguientes datos de mercado y toma una decisión de trading.
{price_block}
**Últimas {prompt_candles} velas (OHLCV):**
{candles_text}
{context_block}
**Indicadores técnicos actuales:**
{indicators_block}
{portfolio_block}
{balance_instruction}
{risk_block}
**MÉTODO DE ANÁLISIS (sigue estos pasos en orden):**

1. **Tendencia general:** ¿El precio está por encima o debajo de SMA200? ¿SMA50 está por encima o debajo de SMA200? (Golden/Death Cross)
2. **Momentum:** ¿El histograma MACD es positivo/negativo y creciente/decreciente? ¿Hay divergencia entre precio y MACD?
3. **Sobrecompra/Sobreventa:** ¿RSI > 70 (sobrecompra) o RSI < 30 (sobreventa)? ¿RSI entre 40-60 (neutral)?
4. **Volatilidad:** ¿El precio está cerca de las bandas de Bollinger? ¿Las bandas se están expandiendo o contrayendo?
5. **Volumen:** ¿El volumen actual es mayor o menor que el promedio? (Confirma la fuerza del movimiento)
6. **Acción de precio:** Analiza las últimas velas OHLCV. ¿Hay patrones de reversión o continuación?

**REGLAS DE DECISIÓN (necesitas al menos 3 confirmaciones):**
- COMPRA (buy): Tendencia alcista (precio > SMA200 o cruzando hacia arriba), MACD creciente, RSI entre 30-65, volumen creciente, precio cerca de banda inferior de Bollinger o rebotando de soporte. **IMPORTANTE: Si ya tienes posición abierta, necesitas al menos 4 confirmaciones fuertes para comprar más. No acumules posiciones solo porque la tendencia es "alcista" — necesitas una razón específica y diferente al ciclo anterior.**
- VENTA (sell): Tendencia bajista o señales de reversión, RSI > 70, MACD decreciente, precio cerca de banda superior de Bollinger, volumen decreciente en subida. Pondera tu ganancia/pérdida actual al decidir. **Si tienes ganancias > 1%, considera tomar beneficios parciales.**
- MANTENER (hold): Cuando las condiciones no han cambiado significativamente desde la última señal, cuando ya tienes posición abierta y no hay señal fuerte nueva, o cuando los indicadores son mixtos. **MANTENER es la opción CORRECTA cuando ya tienes posición y el mercado está lateral o sin cambios claros. NO compres en cada ciclo solo porque hay tendencia alcista general.**

**ANTI-SOBRE-TRADING (MUY IMPORTANTE):**
- Si ya tienes posición abierta y los indicadores no han cambiado drásticamente, la señal correcta es MANTENER (hold).
- NO compres repetidamente solo porque RSI está entre 30-65 y MACD es positivo — eso describe mercado "normal", no una oportunidad de compra.
- Una compra adicional (DCA) solo se justifica si el precio ha bajado significativamente (>2%) desde tu precio promedio de compra, creando una oportunidad real de mejorar tu entrada.

**GESTIÓN DE CAPITAL (OBLIGATORIO):**
- COMPRA: Indica "amount_usdt" (cuántos {quote_currency} invertir). Máximo 30% de tu {quote_currency} disponible ({free_quote:.4f}). No compres si tu balance es < 5 {quote_currency}. Diversifica: monitoreas {num_pairs} pares.
- Alta confianza (>0.85): hasta 25-30% del balance. Media (0.7-0.85): 10-20%. Baja: no compres.
- VENTA: Indica "sell_percentage" (1-100) de tu posición ({holdings:.8f} {base_currency}). Venta parcial para asegurar ganancias, total si tendencia es claramente bajista.
- MANTENER: No incluyas montos.

Responde ÚNICAMENTE con un objeto JSON válido (sin texto adicional):
- Comprar: {{"signal": "buy", "confidence": <0.0-1.0>, "reason": "<análisis técnico conciso en español>", "amount_usdt": <monto>}}
- Vender: {{"signal": "sell", "confidence": <0.0-1.0>, "reason": "<análisis técnico conciso en español>", "sell_percentage": <1-100>}}
- Mantener: {{"signal": "hold", "confidence": <0.0-1.0>, "reason": "<análisis técnico conciso en español>"}}"""


def _extract_json_from_response(content: str) -> Optional[dict]:
    """Extrae y parsea el JSON de la respuesta de la IA (puede venir envuelto en markdown)."""
    if not content or not content.strip():
        return None
    raw = content.strip()
    if "```" in raw:
        parts = raw.split("```")
        for p in parts:
            p = p.strip()
            if p.lower().startswith("json"):
                p = p[4:].strip()
            if p.startswith("{"):
                try:
                    return json.loads(p)
                except json.JSONDecodeError:
                    continue
    if "{" in raw and "}" in raw:
        start = raw.index("{")
        end = raw.rindex("}") + 1
        try:
            return json.loads(raw[start:end])
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _call_openai_compatible(
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
) -> Optional[str]:
    """Llama a una API compatible con OpenAI (OpenAI, Groq u Ollama)."""
    if not _HAS_OPENAI:
        logger.error("Se necesita instalar openai: pip install openai.")
        return None
    try:
        client = OpenAI(base_url=base_url, api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Eres un analista cuantitativo de criptomonedas con experiencia en análisis técnico. "
                        "Tu trabajo es evaluar indicadores técnicos y datos de mercado para generar señales de trading precisas. "
                        "Responde ÚNICAMENTE con un objeto JSON válido, sin texto adicional ni explicaciones fuera del JSON."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=400,
        )
        return (response.choices[0].message.content or "").strip()
    except OpenAIRateLimitError:
        raise
    except OpenAIAPIError:
        raise
    except Exception as e:
        logger.warning("Error en llamada a la IA (API compatible OpenAI): %s", str(e)[:200])
        return None


def _call_gemini(prompt: str, model: str, api_key: Optional[str] = None) -> Optional[str]:
    """Llama a Google Gemini. Requiere pip install google-generativeai."""
    genai = _get_gemini_client()
    if genai is None:
        logger.error("Para usar Gemini instala: pip install google-generativeai.")
        return None
    try:
        genai.configure(api_key=api_key or GOOGLE_API_KEY)
        gemini = genai.GenerativeModel(model)
        response = gemini.generate_content(prompt)
        if response and response.text:
            return response.text.strip()
        return None
    except Exception as e:
        err_msg = str(e)
        logger.warning("Error al llamar Gemini: %s", err_msg[:200])
        if "429" in err_msg or "quota" in err_msg.lower():
            logger.warning(
                "Gemini: cuota o límite de uso superado. El plan gratuito tiene pocas peticiones por minuto. "
                "Aumenta PAIR_DELAY e INTERVAL o revisa la documentación de límites."
            )
        elif "404" in err_msg:
            logger.warning(
                "El modelo '%s' no está disponible. Prueba en .env: GEMINI_MODEL=gemini-2.0-flash o GEMINI_MODEL=gemini-pro.",
                model,
            )
        return None


def get_ai_signal(
    pair: str,
    timeframe: str,
    candles_text: str,
    indicators: dict,
    prompt_candles: int = 5,
    context_summary: Optional[str] = None,
    current_price: Optional[float] = None,
    portfolio_context: Optional[dict] = None,
    stop_loss_percent: Optional[float] = None,
    num_pairs: int = 1,
    ai_config: Optional[dict] = None,
) -> Optional[dict]:
    """
    Envía el prompt a la IA configurada (OpenAI, Groq, Gemini u Ollama), parsea la respuesta
    JSON y retorna el dict validado (signal, confidence, reason, amount_usdt/sell_percentage)
    o None en caso de error.

    ai_config (opcional): dict con claves provider, openai_api_key, groq_api_key,
    google_api_key, ollama_host, openai_model, groq_model, gemini_model, ollama_model.
    Si se provee, se usan esos valores en vez de los del módulo config (thread-safe).
    """
    prompt = build_prompt(
        pair,
        timeframe,
        candles_text,
        indicators,
        prompt_candles,
        context_summary,
        current_price=current_price,
        portfolio_context=portfolio_context,
        stop_loss_percent=stop_loss_percent,
        num_pairs=num_pairs,
    )

    # Resolver configuración de IA: parámetro directo o módulo config
    if ai_config:
        provider = (ai_config.get("provider") or "groq").strip().lower()
        openai_key = ai_config.get("openai_api_key") or ""
        groq_key = ai_config.get("groq_api_key") or ""
        google_key = ai_config.get("google_api_key") or ""
        ollama_host = ai_config.get("ollama_host") or "http://localhost:11434"
        openai_model = ai_config.get("openai_model") or "gpt-4o-mini"
        groq_model = ai_config.get("groq_model") or "llama-3.1-8b-instant"
        gemini_model = ai_config.get("gemini_model") or "gemini-2.0-flash"
        ollama_model = ai_config.get("ollama_model") or "llama2"
    else:
        provider = AI_PROVIDER
        openai_key = OPENAI_API_KEY
        groq_key = GROQ_API_KEY
        google_key = GOOGLE_API_KEY
        ollama_host = OLLAMA_HOST
        openai_model = OPENAI_MODEL
        groq_model = GROQ_MODEL
        gemini_model = GEMINI_MODEL
        ollama_model = OLLAMA_MODEL

    logger.debug("Prompt enviado a la IA (%s) para %s (longitud %d caracteres)", provider, pair, len(prompt))

    model = ""
    content = None

    if provider == "openai":
        if not openai_key:
            logger.error("AI_PROVIDER=openai pero OPENAI_API_KEY no está configurada.")
            return None
        model = openai_model
        try:
            content = _call_openai_compatible(
                base_url="https://api.openai.com/v1",
                api_key=openai_key,
                model=model,
                prompt=prompt,
            )
        except OpenAIRateLimitError:
            logger.warning(
                "OpenAI: cuota o límite superado para %s. Revisa tu plan en la web de OpenAI.",
                pair,
            )
            return None
        except OpenAIAPIError as e:
            logger.warning("Error de la API de OpenAI para %s: %s", pair, getattr(e, "message", str(e))[:150])
            return None

    elif provider == "groq":
        if not groq_key:
            logger.error("AI_PROVIDER=groq pero GROQ_API_KEY no está configurada. Obtén una clave gratis en console.groq.com")
            return None
        model = groq_model
        try:
            content = _call_openai_compatible(
                base_url="https://api.groq.com/openai/v1",
                api_key=groq_key,
                model=model,
                prompt=prompt,
            )
        except OpenAIRateLimitError:
            logger.warning("Groq: límite de uso para %s. Revisa la consola de Groq.", pair)
            return None
        except OpenAIAPIError as e:
            logger.warning("Error de la API de Groq para %s: %s", pair, getattr(e, "message", str(e))[:150])
            return None

    elif provider == "ollama":
        model = ollama_model
        content = _call_openai_compatible(
            base_url=f"{ollama_host}/v1",
            api_key="ollama",
            model=model,
            prompt=prompt,
        )
        if content is None:
            logger.warning(
                "Ollama no respondió para %s. ¿Está en ejecución? Prueba: ollama run %s",
                pair,
                model,
            )

    elif provider == "gemini":
        if not google_key:
            logger.error(
                "AI_PROVIDER=gemini pero GOOGLE_API_KEY no está configurada. "
                "Obtén una clave en Google AI Studio (aistudio.google.com)."
            )
            return None
        model = gemini_model
        content = _call_gemini(prompt, model, api_key=google_key)

    else:
        logger.error("AI_PROVIDER no soportado: %s. Usa: openai, groq, gemini u ollama.", provider)
        return None

    if not content:
        logger.warning("La IA no devolvió respuesta para %s.", pair)
        return None

    data = _extract_json_from_response(content)
    if data is None:
        logger.warning("La respuesta de la IA no es un JSON válido para %s.", pair)
        return None

    validated = validate_ai_signal(data)
    if validated:
        logger.info(
                "IA %s: señal=%s confianza=%.2f razón=%s",
                pair,
                validated["signal"],
                validated["confidence"],
                validated["reason"][:80],
            )
    return validated
