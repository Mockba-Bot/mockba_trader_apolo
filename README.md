# Mockba Trader Binance

Este proyecto es un bot de trading automatizado para Binance Futures que utiliza señales de ML, análisis con LLM y gestión de posiciones.

## Requisitos Previos

- Docker instalado en tu sistema
- Docker Compose instalado
- Una cuenta en Binance con API habilitada
- Una clave API de DeepSeek para análisis LLM
- Un bot de Telegram configurado (opcional, para notificaciones)

## Configuración

### 1. Archivo .env

Crea un archivo `.env` en la raíz del proyecto con las siguientes variables de entorno:

```env
# Claves de Binance
BINANCE_API_KEY=tu_api_key_de_binance
BINANCE_SECRET_KEY=tu_secret_key_de_binance

# Clave de DeepSeek para análisis LLM
DEEP_SEEK_API_KEY=tu_clave_de_deepseek

# Configuración de Telegram (opcional)
API_TOKEN=tu_token_del_bot_de_telegram
TELEGRAM_CHAT_ID=tu_chat_id_de_telegram

# Configuración de Redis (opcional, para caché)
REDIS_URL=redis://localhost:6379

# Configuración del bot
BOT_LANGUAGE=en  # Idioma del bot (en, es, etc.)
APP_PORT=8000  # Puerto para la API FastAPI

# Parámetros de riesgo
RISK_PER_TRADE_PCT=1.5  # Porcentaje de riesgo por trade
MAX_LEVERAGE_HIGH=5
MAX_LEVERAGE_MEDIUM=4
MAX_LEVERAGE_SMALL=3
MICRO_BACKTEST_MIN_EXPECTANCY=0.0025
```

### 2. Archivo llm_prompt_template.txt

Crea un archivo `llm_prompt_template.txt` en la raíz del proyecto con tu plantilla de prompt personalizada para el análisis LLM. Este archivo se monta en el contenedor y puede ser editado sin reconstruir la imagen.

Ejemplo básico:

```
Eres un trader experimentado. Analiza los datos y proporciona una recomendación.
```

### 3. Despliegue con Docker Compose

1. Asegúrate de que Docker y Docker Compose estén instalados y ejecutándose.

2. Navega al directorio del proyecto:

   ```bash
   cd mockba_trader_binance
   ```

3. Ejecuta el contenedor:

   ```bash
   docker compose -f docker-compose-mockba-binance.yml up -d
   ```

   Esto iniciará el bot y Watchtower para actualizaciones automáticas.

4. Para ver los logs:

   ```bash
   docker compose -f docker-compose-mockba-binance.yml logs -f
   ```

5. Para detener:

   ```bash
   docker compose -f docker-compose-mockba-binance.yml down
   ```

## Funcionalidades

- **Señales de ML**: Recibe señales de trading desde una API externa.
- **Análisis LLM**: Utiliza DeepSeek para analizar candles y orderbook antes de ejecutar trades.
- **Gestión de Posiciones**: Monitorea posiciones abiertas y cierra cuando se alcanzan TP/SL.
- **Notificaciones Telegram**: Envía actualizaciones de posiciones al bot de Telegram.
- **Backtesting Micro**: Valida señales con backtesting rápido antes de ejecutar.
- **Persistencia de Liquidez**: Verifica consenso CEX/DEX antes de trades.

## Estructura del Proyecto

- `futures_perps/trade/binance/main.py`: Lógica principal del bot
- `telegram.py`: Bot de Telegram para control manual
- `db/db_ops.py`: Operaciones de base de datos SQLite
- `logs/`: Directorio de logs
- `data/`: Base de datos y archivos persistentes

## Solución de Problemas

- **Error de conexión a Binance**: Verifica tus claves API y permisos.
- **Error de LLM**: Asegúrate de que DEEP_SEEK_API_KEY sea válida.
- **Redis no disponible**: El bot funciona sin Redis, pero sin caché de traducciones.
- **Archivo no encontrado**: Asegúrate de que `llm_prompt_template.txt` exista en la raíz.

## Licencia

Este proyecto es de código abierto. Úsalo bajo tu propio riesgo.</content>
<parameter name="filePath">/home/andres/vsCodeProjects/Python/MockbaV4/mockba_trader_binance/README.md