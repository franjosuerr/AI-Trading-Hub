# AI Trading Hub — Bot de Trading Multi-usuario con IA

Bot de trading que se conecta a **CoinEx**, analiza pares con indicadores técnicos (RSI, MACD, SMA, Bollinger Bands), consulta una **IA** para decidir comprar/vender/mantener, y envía notificaciones a **Telegram**. Todo gestionado desde un **dashboard web** con autenticación.

## Arquitectura

```
┌──────────────┐     ┌──────────────────┐     ┌──────────────┐
│   Frontend   │────▶│   Backend API    │────▶│   CoinEx     │
│   (React)    │     │   (FastAPI)      │     │   Exchange   │
│   :5173      │     │   :8000          │     └──────────────┘
└──────────────┘     │                  │
                     │  Bot Manager     │────▶ Groq / OpenAI /
                     │  (por usuario)   │      Gemini / Ollama
                     │                  │
                     │  SQLite DB       │────▶ Telegram Bot
                     └──────────────────┘
```

## Requisitos

- **Python 3.10+**
- **Node.js 18+** (para el frontend)
- Cuenta en **CoinEx** (API key y secret)
- Al menos **una** API key de IA:
  - **Groq** (gratis) → [console.groq.com](https://console.groq.com)
  - **Google Gemini** (gratis) → [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
  - **Ollama** (local, sin clave) → [ollama.com](https://ollama.com)
  - **OpenAI** (de pago)
- Bot de **Telegram** (token de @BotFather + chat ID de @userinfobot)

## Instalación

### 1. Clonar y entrar al proyecto

```bash
git clone <tu-repo>
cd "Bot Tradding con IA - API"
```

### 2. Backend (Python)

```bash
# Crear entorno virtual
python -m venv venv

# Activar (Windows)
venv\Scripts\activate
# Activar (Linux/Mac)
source venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt
```

### 3. Frontend (React)

```bash
cd frontend
npm install
cd ..
```

### 4. Configuración

Copiar `.env.example` a `.env` y rellenar las credenciales:

```bash
cp .env.example .env
```

> **Nota:** El `.env` es para el bot standalone original. La API web usa la base de datos SQLite para guardar la configuración, que se edita desde el dashboard.

## Ejecución

Abrir **dos terminales**:

**Terminal 1 — Backend API:**
```bash
python -m uvicorn backend.main:app --reload
```

**Terminal 2 — Frontend:**
```bash
cd frontend
npm run dev
```

Abrir el navegador en `http://localhost:5173`

## Login

| Campo | Valor |
|---|---|
| Email | `franjosuerr@gmail.com` |
| Contraseña | `Rolo@100` |

El token JWT dura **24 horas**. Todas las rutas API están protegidas.

## Dashboard

Desde el dashboard puedes:

- **Agregar usuarios/bots**: Cada usuario tiene su propia API key de CoinEx y credenciales de Telegram
- **Iniciar/Detener bots**: Cada bot corre como un task async independiente
- **Configuración Global**: Proveedor de IA, pares, timeframe, intervalos, umbrales, montos por par
- **Cambios en vivo**: Al cambiar la config global, todos los bots activos se reinician automáticamente

## Estructura del proyecto

```
├── backend/
│   ├── main.py              # FastAPI app, middleware JWT, startup
│   ├── database.py          # SQLite (data/trading_bot.db)
│   ├── logger_config.py     # Sistema de logging multi-archivo
│   ├── schemas.py           # Pydantic schemas
│   ├── models/
│   │   └── models.py        # User, GlobalConfig, Trade
│   └── api/
│       ├── auth.py          # Login JWT + middleware de autenticación
│       ├── users.py         # CRUD usuarios + reinicio de bot
│       ├── config.py        # Config global + reinicio de todos los bots
│       ├── control.py       # Start/Stop bots
│       ├── stats.py         # Estadísticas del dashboard
│       └── logs.py          # Endpoint para logs del frontend
│
├── bot/
│   └── bot_manager.py       # Orquestador multi-usuario con trading real
│
├── frontend/
│   └── src/
│       ├── App.jsx          # Dashboard + Login
│       └── utils/logger.js  # Logger del frontend → backend
│
├── ai_advisor.py            # Prompt y llamada a la IA (Groq/OpenAI/Gemini/Ollama)
├── indicators.py            # RSI, MACD, SMA, Bollinger, volumen
├── exchange_client.py       # Conexión CoinEx via ccxt
├── telegram_notifier.py     # Notificaciones Telegram
├── utils.py                 # Formateo, precisión, validación
├── config.py                # Carga de .env (para bot standalone)
├── main.py                  # Bot standalone (sin API)
├── backtest.py              # Backtest histórico
│
├── logs/
│   ├── backend.log          # Logs de la API + uvicorn
│   ├── frontend.log         # Logs del navegador
│   └── bots/
│       └── user_1.log       # Logs del bot del usuario 1
│
├── data/
│   └── trading_bot.db       # Base de datos SQLite
│
├── requirements.txt
├── .env.example
└── .gitignore
```

## Logging

El sistema tiene **3 streams de logs** separados:

| Archivo | Contenido |
|---|---|
| `logs/backend.log` | API requests, errores del servidor, uvicorn access |
| `logs/frontend.log` | Eventos del navegador (navegación, acciones del usuario) |
| `logs/bots/user_{id}.log` | Ciclos de trading por usuario: OHLCV, indicadores, señales IA, órdenes, Telegram |

- Los logs se retienen por **30 días** y se limpian automáticamente al iniciar el servidor
- Cada ciclo de trading se registra con este detalle:

```
========== INICIO DE CICLO #1 | 2026-02-28T21:00:00 ==========
Balance al inicio: USDT=65.32
---------- Par: SOL/USDT ----------
OHLCV: 210 velas | Última: O=84.97 H=85.0 L=83.6 C=83.73
Indicadores: RSI=64.36 MACD_line=0.93 SMA50=80.47 SMA200=82.92
Señal IA: señal=mantener confianza=0.7 razón=La tendencia es lateral...
Telegram: enviando mensaje (476 caracteres)...
Telegram: mensaje enviado OK.
========== FIN DE CICLO | Órdenes ejecutadas: 0 | Señales: 2 ==========
Próximo ciclo en 300 segundos.
```

## Seguridad

- **Autenticación JWT** en todas las rutas API
- **bcrypt** para hash de contraseña (nunca almacenada en texto plano)
- `.env` y bases de datos excluidas del repositorio vía `.gitignore`
- **TEST_MODE**: con `true` no se envían órdenes reales a CoinEx, solo se simulan
- Límite de trades por día por par para evitar sobreoperar

## Bot Standalone (sin API)

Para ejecutar el bot sin el dashboard web:

```bash
python main.py
```

Usa la configuración del archivo `.env`. Detener con `Ctrl+C`.

## Notas

- CoinEx no ofrece testnet público; el "modo test" consiste en **no enviar** órdenes reales
- La IA puede equivocarse; el bot incluye medidas de seguridad pero el trading conlleva riesgo
- Úsalo bajo tu responsabilidad
