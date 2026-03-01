# Checklist: Trading Bot Completo (CoinEx + IA + Telegram)

**Estado:** Implementado. Código en raíz del proyecto; ver README.md para uso.

## Alcance
- Bot de trading que conecta a CoinEx, analiza múltiples pares con indicadores técnicos, usa IA (OpenAI) para señales y notifica por Telegram.
- Modo test: simular órdenes sin enviar a CoinEx (no hay testnet oficial).

## Cambios realizados (todos completados)

### 1. Estructura y configuración
- [x] `config.py`: cargar .env, pares, timeframe, candle_count, prompt_candles, confidence_threshold, order_amount por par, test_mode, interval, pair_delay.
- [x] `logger_config.py`: logging rotativo a `trading_bot.log`, formato timestamp/level/mensaje.
- [x] `.env.example`: COINEX_API_KEY, COINEX_SECRET, OPENAI_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID.

### 2. Exchange (CoinEx)
- [x] `exchange_client.py`: ccxt coinex, fetch OHLCV por par/timeframe, create_order (market/limit), en test_mode no llamar createOrder sino loguear y retornar orden simulada.
- [x] Respetar precision (price, amount) por mercado desde exchange.

### 3. Indicadores técnicos
- [x] `indicators.py`: RSI, MACD (line, signal, histogram), SMA 50/200, Bollinger Bands, volumen medio. Usar pandas + ta (o cálculos simples si ta no está).

### 4. IA (OpenAI)
- [x] `ai_advisor.py`: construir prompt por par (OHLCV + indicadores), llamar API OpenAI, parsear JSON (signal, confidence, reason), validar y manejar errores.

### 5. Telegram
- [x] `telegram_notifier.py`: startup, señales por ciclo (agregadas), órdenes ejecutadas, errores críticos (requests).

### 6. Orquestación y seguridad
- [x] `main.py`: loop cada INTERVAL segundos; por cada par: fetch candles → indicadores → prompt → AI → si signal buy/sell y confidence >= threshold → orden (o simulación); delay entre pares; graceful shutdown (KeyboardInterrupt).
- [x] `utils.py`: validación JSON señal, formateo, precisión.
- [x] Medidas: límite de trades por día por par, precisión CoinEx. STOP_LOSS_PERCENT en config para ampliación futura.

### 7. Backtest
- [x] `backtest.py`: script separado; datos históricos por par, simular decisiones (IA o reglas RSI), métricas por par y globales.

### 8. Entregables
- [x] requirements.txt, .env.example, README.md con instalación y ejecución.
- [x] Comentarios en español en el código.

## Edge cases cubiertos
- API CoinEx/OpenAI caída: log + notificar Telegram, continuar con siguiente par.
- Respuesta AI no JSON válido: log, skip orden, continuar.
- Límite de trades por día por par para evitar sobreoperar.
