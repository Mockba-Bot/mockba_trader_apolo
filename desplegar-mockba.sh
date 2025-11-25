#!/bin/bash

echo "🤖 Bot Mockba Trader - Despliegue Automático"
echo "============================================"

# Colores
ROJO='\033[0;31m'
VERDE='\033[0;32m'
AMARILLO='\033[1;33m'
AZUL='\033[0;34m'
NC='\033[0m'

imprimir_estado() { echo -e "${VERDE}✅ $1${NC}"; }
imprimir_advertencia() { echo -e "${AMARILLO}⚠️  $1${NC}"; }
imprimir_info() { echo -e "${AZUL}💡 $1${NC}"; }
imprimir_error() { echo -e "${ROJO}❌ $1${NC}"; }

# === Helper Functions ===

# For REQUIRED fields (cannot skip)
pedir_obligatorio() {
    local mensaje="$1"
    local var="$2"
    while true; do
        read -p "$mensaje ('c' para cancelar): " entrada
        case "$entrada" in
            c|C)
                imprimir_info "Instalación cancelada por el usuario."
                exit 0
                ;;
            "")
                imprimir_advertencia "Este campo es obligatorio. Por favor, ingrésalo."
                ;;
            *)
                eval "$var='$entrada'"
                return
                ;;
        esac
    done
}

# For OPTIONAL fields (can skip with Enter/x)
pedir_opcional() {
    local mensaje="$1"
    local defecto="$2"
    local var="$3"
    while true; do
        read -p "$mensaje (Enter o 'x' = usar '$defecto', 'c' = cancelar): " entrada
        case "$entrada" in
            c|C)
                imprimir_info "Instalación cancelada por el usuario."
                exit 0
                ;;
            ""|"x"|"X")
                eval "$var='$defecto'"
                return
                ;;
            *)
                eval "$var='$entrada'"
                return
                ;;
        esac
    done
}

# === Main Flow ===

DIRECTORIO_PROYECTO="/opt/mockba-trader"
imprimir_estado "Creando directorio del proyecto: $DIRECTORIO_PROYECTO"
mkdir -p "$DIRECTORIO_PROYECTO"
cd "$DIRECTORIO_PROYECTO" || { imprimir_error "No se pudo acceder a $DIRECTORIO_PROYECTO"; exit 1; }

# === Docker ===
if ! command -v docker &> /dev/null; then
    imprimir_advertencia "Docker no encontrado. Instalando..."
    curl -fsSL https://get.docker.com -o instalar-docker.sh
    sh instalar-docker.sh
    imprimir_estado "Docker instalado correctamente"
else
    imprimir_estado "Docker ya está instalado"
fi

# === Docker Compose ===
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    imprimir_advertencia "Docker Compose no encontrado. Instalando..."
    curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" \
         -o /usr/local/bin/docker-compose
    chmod +x /usr/local/bin/docker-compose
    imprimir_estado "Docker Compose instalado"
else
    imprimir_estado "Docker Compose ya está instalado"
fi

# === Configuración interactiva ===
echo
imprimir_info "🔧 Configuración del Bot - Paso 1: API Keys (obligatorias)"
pedir_obligatorio "🔑 BINANCE_API_KEY" BINANCE_API_KEY
pedir_obligatorio "🔑 BINANCE_SECRET_KEY" BINANCE_SECRET_KEY
pedir_obligatorio "🤖 DEEP_SEEK_API_KEY" DEEP_SEEK_API_KEY

echo
imprimir_info "📱 Configuración del Bot - Paso 2: Telegram (obligatorias)"
pedir_obligatorio "🤖 Telegram API_TOKEN" API_TOKEN
pedir_obligatorio "💬 TELEGRAM_CHAT_ID" TELEGRAM_CHAT_ID

echo
imprimir_info "🌐 Configuración del Bot - Paso 3: Idioma"
pedir_obligatorio "Idioma (es/en)" BOT_LANGUAGE

echo
imprimir_info "⚙️ Configuración del Bot - Paso 4: Parámetros de Trading"
pedir_obligatorio "📊 Riesgo por trade (%) (Ejemplo 1.5)" RISK_PER_TRADE_PCT
pedir_obligatorio "🎚️ Apalancamiento alto (Ejemplo 10)" MAX_LEVERAGE_HIGH
pedir_obligatorio "🎚️ Apalancamiento medio (Ejemplo 5)" MAX_LEVERAGE_MEDIUM
pedir_obligatorio "🎚️ Apalancamiento bajo (Ejemplo 3)" MAX_LEVERAGE_SMALL
pedir_obligatorio "📈 Expectativa mínima backtest (Ejemplo 0.0040)" MICRO_BACKTEST_MIN_EXPECTANCY
pedir_obligatorio "🔢 Máximo trades concurrentes (Ejemplo 5)" MAX_CONCURRENT_TRADES

echo
imprimir_info "📝 Configuración del Bot - Paso 5: Prompt de IA"
pedir_obligatorio "✏️ Prompt personalizado (Ejemplo: 'Eres un experto en trading...')" PROMPT_PERSONALIZADO

# === Guardar archivos ===
imprimir_estado "Creando archivos de configuración..."

cat > docker-compose.yml << EOF
version: '3.8'
services:
  micro-mockba-apolo-futures-bot:
    image: andresdom2004/micro-mockba-apolo-futures-bot:latest
    container_name: micro-mockba-apolo-futures-bot
    restart: always
    env_file:
      - .env
    volumes:
      - ./.env:/app/.env
      - ./prompt.txt:/app/futures_perps/trade/binance/llm_prompt_template.txt

  watchtower:
    image: containrrr/watchtower
    container_name: watchtower-binance
    restart: always
    depends_on:
      - micro-mockba-apolo-futures-bot
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    environment:
      - WATCHTOWER_CLEANUP=true
      - WATCHTOWER_POLL_INTERVAL=300
      - WATCHTOWER_LIFECYCLE_HOOKS=true
      - WATCHTOWER_LABEL_ENABLE=true

  redis:
    image: redis:latest
    container_name: redis-mockba-binance
    restart: always
    ports:
      - "6379:6379"  # Expose Redis on external port 6391
    volumes:
      - redis_data:/data  # Optional: Persist Redis data across restarts

volumes:
  redis_data:  # Define the volume for Redis data persistence        
EOF

cat > .env << EOF
BINANCE_API_KEY=$BINANCE_API_KEY
BINANCE_SECRET_KEY=$BINANCE_SECRET_KEY
DEEP_SEEK_API_KEY=$DEEP_SEEK_API_KEY
API_TOKEN=$API_TOKEN
TELEGRAM_CHAT_ID=$TELEGRAM_CHAT_ID
BOT_LANGUAGE=$BOT_LANGUAGE
APP_PORT=8000
REDIS_URL=redis://redis:6379/0
CPU_COUNT=0
MAX_WORKERS=10
MAX_CONCURRENT_TRADES=$MAX_CONCURRENT_TRADES
RISK_PER_TRADE_PCT=$RISK_PER_TRADE_PCT
MAX_LEVERAGE_HIGH=$MAX_LEVERAGE_HIGH
MAX_LEVERAGE_MEDIUM=$MAX_LEVERAGE_MEDIUM
MAX_LEVERAGE_SMALL=$MAX_LEVERAGE_SMALL
MICRO_BACKTEST_MIN_EXPECTANCY=$MICRO_BACKTEST_MIN_EXPECTANCY
EOF

echo "$PROMPT_PERSONALIZADO" > prompt.txt

imprimir_estado "Archivos creados: .env, docker-compose.yml, prompt.txt"

# === Iniciar ===
imprimir_info "🚀 ¿Deseas iniciar el bot ahora?"
read -p "Escribe 's' para iniciar, cualquier otra tecla para salir sin iniciar: " iniciar
if [[ ! "$iniciar" =~ ^[Ss]$ ]]; then
    imprimir_info "Instalación completada. Puedes iniciar manualmente con: docker-compose up -d"
    exit 0
fi

imprimir_estado "Iniciando el bot..."

if command -v docker-compose &> /dev/null; then
    DOCKER_CMD="docker-compose"
else
    DOCKER_CMD="docker compose"
fi

$DOCKER_CMD up -d

if [ $? -eq 0 ]; then
    echo
    imprimir_estado "✅ ¡Bot iniciado correctamente!"
    echo
    echo "📝 Editar configuración:   nano $DIRECTORIO_PROYECTO/.env"
    echo "✏️  Editar prompt:        nano $DIRECTORIO_PROYECTO/prompt.txt"
    echo "📊 Ver logs:              $DOCKER_CMD logs -f"
    echo "🛑 Detener bot:           $DOCKER_CMD down"
    echo "▶️  Iniciar bot:          $DOCKER_CMD up -d"
    echo
    imprimir_estado "¡Despliegue completado! 🎉"
else
    imprimir_error "❌ Error al iniciar el contenedor. Verifica la configuración."
    exit 1
fi