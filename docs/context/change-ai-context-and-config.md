# Checklist: Configuración y contexto para la IA (compras/ventas)

**Objetivo:** Asegurar que la configuración y el contexto que recibe la IA son suficientes para tomar decisiones de compra/venta de forma consistente.

## Configuración (.env / config.py)

| Variable | Recomendación | Motivo |
|----------|---------------|--------|
| `CANDLE_COUNT` | ≥ 50 (ideal 100 si quieres SMA200 estable) | MACD(12,26,9) y SMA200 necesitan suficientes velas; con 20 muchas veces MACD/SMA200 salen None. |
| `PROMPT_CANDLES` | 10–15 | Más velas en el prompt = mejor contexto para la IA; más de 15 aumenta tokens sin ganancia clara. |
| `TIMEFRAME` | 15m o 1h | 1m es muy ruidoso; 4h/1d menos señales. 15m equilibrado. |
| `CONFIDENCE_THRESHOLD` | 0.7 (o 0.75 más conservador) | Reduce falsos positivos. |
| `STOP_LOSS_PERCENT` | Definido (ej. 2.0) | Para que la IA sepa el riesgo en ventas (incluido en prompt). |

## Contexto actual que recibe la IA

- Par, timeframe.
- Últimas N velas OHLCV (open, high, low, close, volume).
- Resumen de contexto: min/max cierre, precio hace 5 y 10 velas, variación % y tendencia (sube/baja/lateral).
- Indicadores: RSI, MACD (line, signal, histogram), SMA50, SMA200, Bollinger (upper/lower), volumen y media.

## Mejoras aplicadas

- [x] Incluir **precio actual (ticker)** en el prompt, no solo el cierre de la última vela (en mercados rápidos el cierre puede ir retrasado).
- [x] Incluir **stop-loss** en el prompt (ej. "En ventas se considera stop-loss al X%; sé conservador con el riesgo.").
- [x] Añadir instrucción de **conservadurismo**: "Solo compra o vende si la señal es clara; en duda, mantén (hold)."
- [x] Pasar desde `main.py`: precio actual, balance (USDT + base) y STOP_LOSS_PERCENT a `get_ai_signal` / `build_prompt`.
- [x] Incluir balance disponible (quote + base) en el prompt para que la IA evite sugerir compra sin USDT o venta sin activo.

## Resumen

Tras los cambios, el contexto es **suficiente** para que la IA tome decisiones de compra/venta con: precio en tiempo casi real, tendencia, indicadores, riesgo (stop-loss) e instrucción de ser conservadora. Revisar `.env` para que `CANDLE_COUNT` sea al menos 50.
