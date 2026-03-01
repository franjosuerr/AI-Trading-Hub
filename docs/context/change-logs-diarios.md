# Checklist: Logs diarios

## Objetivo
Generar archivos de log rotados por día (un archivo por día, rotación a medianoche).

## Cambios realizados
- [x] Añadir en config: LOG_DIR, LOG_DAILY, LOG_BACKUP_DAYS; LOG_FILE como nombre base.
- [x] En logger_config: TimedRotatingFileHandler cuando LOG_DAILY=true (midnight, LOG_BACKUP_DAYS); RotatingFileHandler si LOG_DAILY=false; guardar en LOG_DIR; mantener consola.
- [x] Actualizar .env.example con LOG_DIR, LOG_DAILY, LOG_BACKUP_DAYS.
- [x] Documentar en README (tabla de config, estructura, sección Logs).

---

# Revisión de fallos en logs (post-análisis)

## Problemas detectados en trading_bot.log
1. **Telegram**: timeout y, sobre todo, **fuga de token** en el log (URL completa con token).
2. **CoinEx**: NetworkError / getaddrinfo failed (red o DNS).
3. **OpenAI**: 429 insufficient_quota (cuota/crédito agotado).

## Correcciones aplicadas
- [x] **telegram_notifier.py**: No registrar nunca URL ni token. Mensaje seguro con _safe_telegram_error_message(); timeout 15s; warning en lugar de exception (sin traceback).
- [x] **exchange_client.py**: Capturar ccxt.NetworkError y ccxt.ExchangeError; mensaje claro tipo "Error de red o DNS al conectar con CoinEx... Comprueba tu conexión"; traceback solo en DEBUG.
- [x] **ai_advisor.py**: Capturar RateLimitError y APIError de OpenAI; mensaje claro para cuota/429 sin volcar respuesta completa; traceback solo en DEBUG.
