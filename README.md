# Mockba Trader Apolo

Este proyecto es un bot de trading automatizado para Apolo Futures que utiliza señales de ML, análisis con LLM y gestión de posiciones.

## Requisitos Previos

- Docker instalado en tu sistema
- Docker Compose instalado
- Una cuenta en Apolo con API habilitada
- Una clave API de DeepSeek para análisis LLM
- Un bot de Telegram configurado (opcional, para notificaciones)

## Configuración

### 1. Archivo .env

Crea un archivo `.env` en la raíz del proyecto con las siguientes variables de entorno:

```env
# Claves de Apolo
Apolo_API_KEY=tu_api_key_de_Apolo
Apolo_SECRET_KEY=tu_secret_key_de_Apolo

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
   cd mockba_trader_Apolo
   ```

3. Ejecuta el contenedor:

   ```bash
   docker compose -f docker-compose-mockba-Apolo.yml up -d
   ```

   Esto iniciará el bot y Watchtower para actualizaciones automáticas.

4. Para ver los logs:

   ```bash
   docker compose -f docker-compose-mockba-Apolo.yml logs -f
   ```

5. Para detener:

   ```bash
   docker compose -f docker-compose-mockba-Apolo.yml down
   ```

## Funcionalidades

- **Señales de ML**: Recibe señales de trading desde una API externa.
- **Análisis LLM**: Utiliza DeepSeek para analizar candles y orderbook antes de ejecutar trades.
- **Gestión de Posiciones**: Monitorea posiciones abiertas y cierra cuando se alcanzan TP/SL.
- **Notificaciones Telegram**: Envía actualizaciones de posiciones al bot de Telegram.
- **Backtesting Micro**: Valida señales con backtesting rápido antes de ejecutar.
- **Persistencia de Liquidez**: Verifica consenso CEX/DEX antes de trades.

## Estructura del Proyecto

- `futures_perps/trade/apolo/main.py`: Lógica principal del bot
- `telegram.py`: Bot de Telegram para control manual
- `db/db_ops.py`: Operaciones de base de datos SQLite
- `logs/`: Directorio de logs
- `data/`: Base de datos y archivos persistentes

## Solución de Problemas

- **Error de conexión a Apolo**: Verifica tus claves API y permisos.
- **Error de LLM**: Asegúrate de que DEEP_SEEK_API_KEY sea válida.
- **Redis no disponible**: El bot funciona sin Redis, pero sin caché de traducciones.
- **Archivo no encontrado**: Asegúrate de que `llm_prompt_template.txt` exista en la raíz.


# 🤖 Guía Completa de Configuración

Este documento te guiará paso a paso para desplegar tu propio **Mockba Trader Bot** en un VPS usando Docker, conectado a Apolo, DeepSeek y Telegram.

---

## 📋 Índice

1. [Crear un VPS en DigitalOcean](#-crear-un-vps-en-digitalocean)  
2. [Configurar Bot de Telegram](#-configurar-bot-de-telegram)  
3. [Obtener API Keys de Apolo](#-obtener-api-keys-de-apolo)  
4. [Obtener API Key de DeepSeek](#-obtener-api-key-de-deepseek)  
5. [⚙️ Configuración del Bot](#️-configuración-del-bot) 
---

## 🖥️ Crear un VPS en DigitalOcean

### Paso a paso:

1. **Crear cuenta en DigitalOcean**  
   - Regístrate y obtén **$200 de crédito gratis por 60 días**.

2. **Crear Droplet**  
   - Ve a **"Droplets" → "Create Droplet"**  
   - **Choose an image**: Haz clic en **"Marketplace"** → busca **"Docker"** → selecciona **"Docker on Ubuntu"**  
   - **Choose a plan**:  
     - Plan: **Basic**  
     - CPU Option: **Regular Intel with SSD**  
     - Precio: **$6/mes** (suficiente para este bot)  
   - **Authentication**:  
     - Opción recomendada: **Password** (más fácil para principiantes)  
     - Opción avanzada: **SSH Key** (más segura)  
   - Haz clic en **"Create Droplet"**

3. **Acceder a tu VPS**  
   - Espera 1–2 minutos a que el Droplet se cree.  
   - **Opción 1 (consola web)**: Haz clic en **"Console"** desde el panel de DigitalOcean.  
   - **Opción 2 (SSH)**:  
     ```bash
     ssh root@TU_IP_DEL_DROPLET
     ```

---

## 🤖 Configurar Bot de Telegram

1. **Crear Bot con @BotFather**  
   - Abre Telegram y busca **@BotFather**  
   - Envía `/start` y luego `/newbot`  
   - Sigue las instrucciones:
     - **Nombre del bot** (visible para usuarios): `Mockba Trader Bot`  
     - **Username del bot** (debe terminar en `bot`): `mockba_trader_bot`  
   - **Guarda el API Token** que te proporciona BotFather.  
     Ejemplo: `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`

2. **Obtener tu Chat ID**  
   - Busca tu nuevo bot en Telegram y envía `/start`  
   - Abre en tu navegador (reemplaza `<TU_TOKEN>`):  
     ```
     https://api.telegram.org/bot<TU_TOKEN>/getUpdates
     ```
   - Busca el campo `"id"` en la respuesta JSON y copia el número.  
   - **Alternativa rápida**: usa [@userinfobot](https://t.me/userinfobot) para obtener tu ID.

---

## 🔑 Obtener API Keys de Apolo

1. Inicia sesión en [Apolo](https://dex.apolopay.app/)
2. Haz clic en Portafolio → **"API Keys"**
3. **Crear nueva API**:
   - Nombre: `Mockba Trader Bot`
   - Confirmar
4. **Permisos recomendados**:
   - ✅ **Enable Reading**  
   - ✅ **Enable Trading**  
   - ✅ **Restringir IP opcional**  
5. **Guarda ambas claves**:
   - `API Key`: ej. `abc123def456`  
   - `Secret Key`: cadena más larga (¡NO la compartas!)

---

## 🔮 Obtener API Key de DeepSeek

1. Ve a [DeepSeek](https://platform.deepseek.com/)
2. Regístrate o inicia sesión
3. Ve a **"API Management"** o **"API Keys"**
4. Crea una nueva clave
5. **Copia y guarda** la API Key generada

> ⚠️ Esta clave es necesaria para el análisis de señales con LLM.

---

## ⚙️ Configuración del Bot

Después de clonar e instalar el proyecto, edita el archivo de entorno:

nano /opt/mockba-trader/.env

---

## 📋 Requisitos del VPS

- **Sistema operativo**: Debian 13 (Trixie) o superior ✅  
  _(Ubuntu también funciona, pero Debian 13+ es lo recomendado para estabilidad)_
- **Región**: Frankfurt (`FRA1`) u otra **fuera de EE.UU.**  
- **RAM**: Mínimo 1 GB  
- **Disco**: 25 GB SSD  
- **Acceso**: `root` o usuario con `sudo`

> 💡 ¿Usas DigitalOcean? Selecciona **Debian 13** como imagen base (no uses "Docker on Ubuntu" si prefieres Debian).

---

## 🚀 Despliegue Automático (Recomendado)

Ejecuta este comando **una sola vez** en tu VPS recién creado:

# 1. Download
curl -fsSL https://raw.githubusercontent.com/Mockba-Bot/mockba_trader_apolo/main/desplegar-mockba.sh -o desplegar-mockba.sh

# 2. Make it executable
chmod +x desplegar-mockba.sh

# 3. Run it (with sudo if writing to /opt/)
sudo ./desplegar-mockba.sh


## Licencia

Este proyecto es de código abierto. Úsalo bajo tu propio riesgo. MIT Licence

