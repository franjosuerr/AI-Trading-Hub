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
    balance_hint: Optional[str] = None,
    stop_loss_percent: Optional[float] = None,
) -> str:
    """
    Construye el prompt para la IA con par, timeframe, últimas velas OHLCV,
    resumen de contexto (tendencia, máximos/mínimos), indicadores, precio actual,
    opcional balance y stop-loss.
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

    balance_block = ""
    if balance_hint and balance_hint.strip():
        balance_block = f"\n**Saldo disponible (referencia):** {balance_hint.strip()}\n"

    risk_block = ""
    if stop_loss_percent is not None and stop_loss_percent > 0:
        risk_block = f"\nEn ventas se considera stop-loss al {stop_loss_percent}%; sé conservador con el riesgo a la baja.\n"

    return f"""Eres un asistente de trading conciso. Analiza los siguientes datos del par {pair} (timeframe: {timeframe}).
{price_block}
**Últimas {prompt_candles} velas (OHLCV):**
{candles_text}
{context_block}
**Indicadores técnicos actuales:**
{indicators_block}
{balance_block}
{risk_block}
Instrucción: solo compra o vende si la señal es clara; en duda, mantén (hold). Considera velas recientes, tendencia e indicadores. ¿Debo comprar, vender o mantener este par? Responde ÚNICAMENTE con un objeto JSON, sin otro texto. Estructura exacta (usa "buy", "sell" o "hold" en signal; la explicación en "reason" en español):
{{"signal": "buy" | "sell" | "hold", "confidence": <número entre 0 y 1>, "reason": "<explicación breve en una frase, en español>"}}"""


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
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=256,
        )
        return (response.choices[0].message.content or "").strip()
    except OpenAIRateLimitError:
        raise
    except OpenAIAPIError:
        raise
    except Exception as e:
        logger.warning("Error en llamada a la IA (API compatible OpenAI): %s", str(e)[:200])
        return None


def _call_gemini(prompt: str, model: str) -> Optional[str]:
    """Llama a Google Gemini. Requiere pip install google-generativeai."""
    genai = _get_gemini_client()
    if genai is None:
        logger.error("Para usar Gemini instala: pip install google-generativeai.")
        return None
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
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
    balance_hint: Optional[str] = None,
    stop_loss_percent: Optional[float] = None,
) -> Optional[dict]:
    """
    Envía el prompt a la IA configurada (OpenAI, Groq, Gemini u Ollama), parsea la respuesta
    JSON y retorna el dict validado (signal, confidence, reason) o None en caso de error.
    """
    prompt = build_prompt(
        pair,
        timeframe,
        candles_text,
        indicators,
        prompt_candles,
        context_summary,
        current_price=current_price,
        balance_hint=balance_hint,
        stop_loss_percent=stop_loss_percent,
    )
    logger.debug("Prompt enviado a la IA (%s) para %s (longitud %d caracteres)", AI_PROVIDER, pair, len(prompt))

    model = ""
    content = None

    if AI_PROVIDER == "openai":
        if not OPENAI_API_KEY:
            logger.error("AI_PROVIDER=openai pero OPENAI_API_KEY no está configurada.")
            return None
        model = OPENAI_MODEL
        try:
            content = _call_openai_compatible(
                base_url="https://api.openai.com/v1",
                api_key=OPENAI_API_KEY,
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

    elif AI_PROVIDER == "groq":
        if not GROQ_API_KEY:
            logger.error("AI_PROVIDER=groq pero GROQ_API_KEY no está configurada. Obtén una clave gratis en console.groq.com")
            return None
        model = GROQ_MODEL
        try:
            content = _call_openai_compatible(
                base_url="https://api.groq.com/openai/v1",
                api_key=GROQ_API_KEY,
                model=model,
                prompt=prompt,
            )
        except OpenAIRateLimitError:
            logger.warning("Groq: límite de uso para %s. Revisa la consola de Groq.", pair)
            return None
        except OpenAIAPIError as e:
            logger.warning("Error de la API de Groq para %s: %s", pair, getattr(e, "message", str(e))[:150])
            return None

    elif AI_PROVIDER == "ollama":
        # Ollama local: no requiere API key
        model = OLLAMA_MODEL
        content = _call_openai_compatible(
            base_url=f"{OLLAMA_HOST}/v1",
            api_key="ollama",  # Ollama no lo usa, pero el cliente lo pide
            model=model,
            prompt=prompt,
        )
        if content is None:
            logger.warning(
                "Ollama no respondió para %s. ¿Está en ejecución? Prueba: ollama run %s",
                pair,
                model,
            )

    elif AI_PROVIDER == "gemini":
        if not GOOGLE_API_KEY:
            logger.error(
                "AI_PROVIDER=gemini pero GOOGLE_API_KEY no está configurada. "
                "Obtén una clave en Google AI Studio (aistudio.google.com)."
            )
            return None
        model = GEMINI_MODEL
        content = _call_gemini(prompt, model)

    else:
        logger.error("AI_PROVIDER no soportado: %s. Usa: openai, groq, gemini u ollama.", AI_PROVIDER)
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
