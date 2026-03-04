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
    recent_signals: Optional[list] = None,
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

        total_capital = free_quote + invested
        portfolio_lines = [
            f"\n**Tu portafolio actual (cuenta real):**",
            f"  - {quote_currency} disponible: {free_quote:.4f} {quote_currency} (Capital Total Est: {total_capital:.4f})",
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

    # --- Bloque de historial de señales recientes ---
    signal_history_block = ""
    if recent_signals and len(recent_signals) > 0:
        hist_lines = ["\n**Historial de señales recientes (ciclos anteriores):**"]
        for i, sig in enumerate(reversed(recent_signals[-5:]), 1):
            sig_label = {"buy": "COMPRAR", "sell": "VENDER", "hold": "MANTENER"}.get(sig.get("signal", ""), sig.get("signal", ""))
            price_str = f" @ {sig['price']:.2f}" if sig.get("price") else ""
            hist_lines.append(
                f"  - Hace {i} ciclo(s): {sig_label} (confianza {sig.get('confidence', 0):.2f}){price_str} — {sig.get('reason', '')[:80]}"
            )
        recent_buys = sum(1 for s in recent_signals[-5:] if s.get("signal") == "buy")
        recent_sells = sum(1 for s in recent_signals[-5:] if s.get("signal") == "sell")
        recent_holds = sum(1 for s in recent_signals[-5:] if s.get("signal") == "hold")
        hist_lines.append(f"  Resumen últimos {len(recent_signals[-5:])} ciclos: {recent_buys} compras, {recent_sells} ventas, {recent_holds} mantener")
        if recent_buys >= 3:
            hist_lines.append(f"  ⚠️ ALERTA: Ya compraste {recent_buys} veces en los últimos ciclos. NO sigas comprando a menos que el precio haya caído >3% desde tu última compra.")
        signal_history_block = "\n".join(hist_lines) + "\n"

    # --- Bloque de análisis pre-calculado (datos objetivos para la IA) ---
    analysis_items = []
    rsi = indicators.get("rsi")
    if rsi is not None:
        if rsi > 70:
            analysis_items.append(f"  - RSI={rsi:.1f} → SOBRECOMPRA (señal de venta)")
        elif rsi > 60:
            analysis_items.append(f"  - RSI={rsi:.1f} → Zona alta (precaución, cerca de sobrecompra)")
        elif rsi < 30:
            analysis_items.append(f"  - RSI={rsi:.1f} → SOBREVENTA (posible oportunidad de compra)")
        elif rsi < 45:
            analysis_items.append(f"  - RSI={rsi:.1f} → Zona baja (posible oportunidad)")
        else:
            analysis_items.append(f"  - RSI={rsi:.1f} → Zona NEUTRAL (NO es señal de compra por sí solo)")

    bb_upper = indicators.get("bb_upper")
    bb_lower = indicators.get("bb_lower")
    if bb_upper and bb_lower and current_price:
        bb_range = bb_upper - bb_lower
        if bb_range > 0:
            bb_pct = (current_price - bb_lower) / bb_range * 100
            analysis_items.append(f"  - Posición en Bollinger: {bb_pct:.0f}% (0%=banda inferior, 50%=medio, 100%=banda superior)")
            if bb_pct > 80:
                analysis_items.append(f"    → Precio CERCA DE BANDA SUPERIOR: señal de posible venta")
            elif bb_pct < 20:
                analysis_items.append(f"    → Precio CERCA DE BANDA INFERIOR: posible zona de compra si otros indicadores confirman")
            else:
                analysis_items.append(f"    → Precio en zona MEDIA de Bollinger: NO es señal de compra ni venta por Bollinger")

    ema200 = indicators.get("ema200")
    ema50 = indicators.get("ema50")
    if current_price and ema200:
        diff_200 = (current_price - ema200) / ema200 * 100
        analysis_items.append(f"  - Precio vs EMA200: {diff_200:+.2f}% ({'por encima' if diff_200 > 0 else 'por debajo'})")
    if current_price and ema50:
        diff_50 = (current_price - ema50) / ema50 * 100
        analysis_items.append(f"  - Precio vs EMA50: {diff_50:+.2f}% ({'por encima' if diff_50 > 0 else 'por debajo'})")
    if ema50 and ema200:
        if ema50 > ema200:
            analysis_items.append("  - EMA50 > EMA200: Cruce alcista (tendencia alcista)")
        else:
            analysis_items.append("  - EMA50 < EMA200: Cruce bajista (tendencia bajista — precaución)")

    macd_hist = indicators.get("macd_histogram")
    if macd_hist is not None:
        if macd_hist > 0:
            analysis_items.append(f"  - MACD histograma: +{macd_hist:.4f} (momentum positivo)")
        else:
            analysis_items.append(f"  - MACD histograma: {macd_hist:.4f} (momentum negativo)")

    vol = indicators.get("volume")
    vol_avg = indicators.get("volume_avg")
    if vol is not None and vol_avg is not None and vol_avg > 0:
        vol_ratio = vol / vol_avg
        analysis_items.append(f"  - Volumen vs promedio: {vol_ratio:.2f}x {'(ALTO — confirma fuerza)' if vol_ratio > 1.5 else '(BAJO — sin fuerza)' if vol_ratio < 0.5 else '(normal)'}")

    if holdings > 0 and avg_entry > 0 and current_price:
        entry_diff = (current_price - avg_entry) / avg_entry * 100
        analysis_items.append(f"  - Precio actual vs tu entrada: {entry_diff:+.2f}% {'(GANANCIA)' if entry_diff > 0 else '(PÉRDIDA)'}")
        if entry_diff > 1.5:
            analysis_items.append(f"    → Ganancia > 1.5%: Considera tomar beneficios parciales (VENDER 25-50%)")
        elif entry_diff < -(stop_loss_percent or 2.0):
            analysis_items.append(f"    → Pérdida supera stop-loss ({stop_loss_percent or 2.0}%): Considera VENDER para proteger capital")

    analysis_block = ""
    if analysis_items:
        analysis_block = "\n**Análisis pre-calculado (datos objetivos — NO los ignores):**\n" + "\n".join(analysis_items) + "\n"

    # --- Prompt Profesional y Estructurado (Estilo Chain-of-Thought) ---

    return f"""You are a strict, risk-averse Institutional Crypto Trading Algorithm.
Your goal is CAPITAL PRESERVATION first, profit second.
You DO NOT hallucinate. You act ONLY on the provided data.
If indicators are neutral or conflicting, the DEFAULT action is HOLD.

### 1. MARKET DATA (FACTS - DO NOT IGNORE)
- **Pair**: {pair} (Timeframe: {timeframe})
- **Current Price**: {current_price}
- **Indicators**:
{indicators_block}
{analysis_block}

### 2. PORTFOLIO STATE (FACTS)
- **Base Asset ({base_currency}) Holdings**: {holdings:.8f}
{portfolio_block}
{balance_instruction}

### 3. RECENT ACTIVITY
{signal_history_block}
{risk_block}

### 4. TRADING RULES (EXECUTE IN ORDER)

**SCENARIO A: TREND FOLLOWING (Bullish Market)**
*Goal: Ride an established uptrend.*
- **BUY SIGNAL** requires ALL of these:
  1. Price > EMA50 AND EMA50 > EMA200 (Bullish trend).
  2. RSI > 50 and rising (Momentum).
  3. MACD Histogram > 0 AND MACD Line > Signal Line.
  4. Bollinger Bands are expanded/expanding upwards.
- **Position Sizing:** IF Scenario A met -> Allocate EXACTLY 2% of Total Est Capital.

**SCENARIO B: REVERSAL OPPORTUNITY (Bearish Market Bounce)**
*Goal: Catch a bounce in an oversold downtrend.*
- **BUY SIGNAL** requires ALL of these:
  1. Bearish trend: Price < EMA50 AND EMA50 < EMA200.
  2. RSI < 30 (Oversold).
  3. Price touches or pierces the Lower Bollinger Band.
  4. MACD Histogram shows decreasing negative momentum (e.g. flattening or turning up) OR Volume > Average Volume (Exhaustion).
- **Position Sizing:** IF Scenario B met -> Allocate EXACTLY 1% of Total Est Capital (Lower Risk).

**SCENARIO C: HAVE POSITION (Holdings > 0)**
*Goal: Manage risk and take profit. Evaluate these Exit Rules.*
- **SELL SIGNAL** requires ANY of these:
  1. **Stop Loss**: PnL < -{stop_loss_percent or 2.0}% (MANDATORY SELL TO PRESERVE CAPITAL).
  2. **Dynamic Take Profit (Trailing Stop)**: If PnL > 2.0%, and Price drops by 1% from its recent local peak, you MUST SELL.
  3. **Alternative Take Profit**: Price reaches or exceeds the Upper Bollinger Band OR hits a major Resistance Zone.
  4. **Momentum Exit**: MACD falls below Signal Line OR RSI drops below 50.
- **IF NONE MET, KEEP HOLDING.**

**DEFAULT ACTION: HOLD**
If NO buy scenario is fully met and NO sell scenario is fully met, your signal MUST be HOLD.

### 5. REQUIRED OUTPUT FORMAT
Response must be a SINGLE JSON object with this exact structure. 
"reason" must explicitly cite the numbers (e.g. "Price is above EMA50, RSI is 42").

{{
  "signal": "buy" | "sell" | "hold",
  "confidence": 0.0 to 1.0,
  "reason": "Step-by-step logic citing specific indicator values",
  "amount_usdt": (for buy: the exact USDT amount calculated based on rule A/B; ensure it does not exceed free_quote),
  "sell_percentage": (for sell: 1-100)
}}
"""


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
    recent_signals: Optional[list] = None,
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
        recent_signals=recent_signals,
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
