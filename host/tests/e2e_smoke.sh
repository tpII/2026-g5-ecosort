#!/usr/bin/env bash
# Prueba de humo end-to-end de host/: broker local + adapter + dashboard, sin Pi.
# Corre igual en tu máquina (`bash host/tests/e2e_smoke.sh`, necesita Docker) y en CI.
#
# Usa un proyecto de Compose propio (-p) y puertos altos: no pisa un stack de
# desarrollo que tengas levantado ni borra sus datos.
set -euo pipefail

cd "$(dirname "$0")/.."   # host/
export DASHBOARD_PORT="${DASHBOARD_PORT:-18080}" MQTT_PORT="${MQTT_PORT:-18830}"
COMPOSE="docker compose -p ecosort-host-smoke -f docker-compose.yml -f docker-compose.dev.yml"
API="http://127.0.0.1:${DASHBOARD_PORT}"

EVENTO='{"evento_id":"00000000-0000-0000-0000-000000000001","dispositivo_id":"ecosort-01","ts":"2026-01-01T00:00:00.000+00:00","clase":"plastico","confianza":0.93,"compuerta":1,"latencia_ms":31.2,"modelo":"smoke"}'

cleanup() {
  local status=$?
  if [ "$status" -ne 0 ]; then
    echo "=== FALLÓ (exit $status) — logs de los servicios ==="
    $COMPOSE logs --no-color || true
  fi
  $COMPOSE down -v >/dev/null 2>&1 || true
  exit "$status"
}
trap cleanup EXIT

fail() { echo "FALLA: $*"; exit 1; }

# Estas funciones capturan la salida en una variable antes de grep: con `pipefail`,
# `curl | grep -q` falla por SIGPIPE en cuanto grep encuentra el patrón y sale.
log_has() { local out; out=$($COMPOSE logs --no-color "$1" 2>&1) || return 1; grep -q "$2" <<<"$out"; }
resumen_has() { local body; body=$(curl -sf "$API/api/resumen") || return 1; grep -q "$1" <<<"$body"; }

wait_for() {  # wait_for "<descripción>" <segundos> <comando...>
  local desc=$1 max=$2; shift 2
  for _ in $(seq 1 "$max"); do
    if "$@" >/dev/null 2>&1; then echo "ok: $desc"; return 0; fi
    sleep 1
  done
  fail "timeout esperando: $desc"
}

publicar() { $COMPOSE exec -T mosquitto mosquitto_pub -h localhost -q 1 -t ecosort/ecosort-01/eventos -m "$EVENTO"; }

echo "== 1) el adapter arranca SIN broker: no debe caerse y debe avisar que reintenta =="
$COMPOSE up -d --build --no-deps adapter
sleep 6
adapter_id=$($COMPOSE ps -q adapter)
reinicios=$(docker inspect -f '{{.RestartCount}}' "$adapter_id")
[ "$reinicios" = "0" ] || fail "el adapter se reinició $reinicios veces sin broker (debería reintentar la conexión, no morir)"
log_has adapter "reintento" || fail "el adapter no avisó que estaba reintentando la conexión"
echo "ok: adapter vivo y reintentando"

echo "== 2) aparece el broker (+ dashboard): deben conectarse solos =="
$COMPOSE up -d --build
wait_for "adapter conectado al broker" 60 log_has adapter "conectado al broker"
wait_for "dashboard conectado al broker" 60 log_has dashboard "conectado al broker"
wait_for "API del dashboard responde" 60 curl -sf "$API/api/resumen"
pagina=$(curl -sf "$API/") || fail "el dashboard no sirvió la página"
grep -q "EcoSort" <<<"$pagina" || fail "la página del dashboard no tiene el frontend esperado"
echo "ok: el dashboard sirve el frontend"

echo "== 3) un evento con el formato real llega a la API =="
publicar
wait_for "total = 1" 30 resumen_has '"total": 1'
resumen_has '"plastico": 1' || fail "el evento no quedó contado como plastico"
echo "ok: evento publicado -> adapter -> SQLite -> API"

echo "== 4) el mismo evento_id repetido (QoS 1 puede duplicar) no se cuenta dos veces =="
publicar
sleep 3
resumen_has '"total": 1' || fail "un evento duplicado se contó dos veces"
echo "ok: dedupe por evento_id"

echo "OK — smoke test del host completo"
