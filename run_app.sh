#!/usr/bin/env bash
# Starts the Aktywny Kraków app locally (branch raf):
#   OTP (Docker, :8080) -> slider presets -> backend (FastAPI, :8000) -> frontend (Vite, :5173) -> browser.
# Ctrl+C stops backend and frontend (OTP keeps running; stop it with: docker stop otp).
#
# Usage:  ./run_app.sh
#   NO_OPEN=1   do not open the browser
#   SKIP_GA=1   do not compute missing slider presets (backend then uses built-in fallback presets)
# Needs:  python3, docker (OTP container "otp", see docs/OTP_QUICKSTART.md);
#         Node >= 20.19 (downloaded automatically to ~/.cache if missing).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend/mApka_frontend"
LOGS="$ROOT/.run"
VENV="$ROOT/.venv"
NODE_DIR="$HOME/.cache/hy2026/node22"
OTP_URL="${OTP_URL:-http://localhost:8080/otp/gtfs/v1}"
BACKEND_PORT=8000
FRONTEND_PORT=5173
mkdir -p "$LOGS"

say() { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m!!\033[0m %s\n' "$*" >&2; exit 1; }

[ -f "$BACKEND/app/main.py" ] && [ -f "$FRONTEND/package.json" ] && [ -d "$ROOT/optimizer" ] \
  || die "Brak backend/, frontend/mApka_frontend/ lub optimizer/ — jesteś na gałęzi raf z najnowszymi zmianami? (git switch raf && git pull)"

for port in $BACKEND_PORT $FRONTEND_PORT; do
  if curl -s -o /dev/null -m 1 "http://127.0.0.1:$port/"; then
    die "Port $port jest zajęty (inna instancja?). Zamknij ją i spróbuj ponownie."
  fi
done

# --- OTP ---------------------------------------------------------------------
otp_up() {
  curl -s -o /dev/null -m 3 -X POST "$OTP_URL" -H 'Content-Type: application/json' \
    -d '{"query":"{serviceTimeRange{start}}"}'
}
if otp_up; then
  say "OTP działa ($OTP_URL)"
elif command -v docker >/dev/null && docker inspect otp >/dev/null 2>&1; then
  say "Uruchamiam kontener OTP (docker start otp) — ok. 30–60 s"
  docker start otp >/dev/null
  for _ in $(seq 1 60); do otp_up && break; sleep 2; done
  if otp_up; then say "OTP gotowy"; else warn "OTP nie odpowiada — trasy nie będą działać (docker logs otp)"; fi
else
  warn "Brak OTP na $OTP_URL i brak kontenera 'otp' — zob. docs/OTP_QUICKSTART.md. Trasy nie będą działać."
fi

# --- Python env (backend + optimizer) ------------------------------------------
if [ ! -x "$VENV/bin/uvicorn" ] || [ "$BACKEND/requirements.txt" -nt "$VENV/.installed" ]; then
  say "Tworzę .venv i instaluję zależności backendu"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q -r "$BACKEND/requirements.txt"
  touch "$VENV/.installed"
fi

# --- slider presets (optimizer quick run) ----------------------------------------
for variant in bike walk; do
  f="$ROOT/optimizer/out/quick_$variant/slider.json"
  if [ ! -f "$f" ]; then
    if [ -n "${SKIP_GA:-}" ] || ! otp_up; then
      warn "Brak $f — backend użyje wbudowanych presetów (SKIP_GA albo brak OTP)."
    else
      say "Liczę presety suwaka ($variant, quick ~1 min; log: .run/ga_$variant.log)"
      (cd "$ROOT" && "$VENV/bin/python" -m optimizer.run_ga --mode quick --seed 1 \
        --variant "$variant" --out "optimizer/out/quick_$variant") > "$LOGS/ga_$variant.log" 2>&1 \
        || warn "run_ga ($variant) nie powiódł się — zob. .run/ga_$variant.log; backend użyje presetów zapasowych"
    fi
  fi
done

# --- Node >= 20.19 (Vite 8) -------------------------------------------------
node_ok() {
  command -v node >/dev/null || return 1
  node -e 'const [a,b]=process.versions.node.split(".").map(Number);process.exit(a>22||(a===22&&b>=12)||(a===20&&b>=19)||a===21?0:1)'
}
if ! node_ok; then
  if [ ! -x "$NODE_DIR/bin/node" ]; then
    say "Node $(node -v 2>/dev/null || echo brak) jest za stary — pobieram przenośny Node 22 do $NODE_DIR"
    V=$(curl -s https://nodejs.org/dist/index.json | python3 -c \
      "import sys,json;print([r['version'] for r in json.load(sys.stdin) if r['version'].startswith('v22.')][0])")
    TMP=$(mktemp -d)
    curl -sL "https://nodejs.org/dist/$V/node-$V-linux-x64.tar.xz" | tar -xJ -C "$TMP"
    mkdir -p "$(dirname "$NODE_DIR")" && rm -rf "$NODE_DIR" && mv "$TMP/node-$V-linux-x64" "$NODE_DIR"
  fi
  export PATH="$NODE_DIR/bin:$PATH"
fi
say "Node $(node -v)"

if [ ! -d "$FRONTEND/node_modules/.bin" ] || [ "$FRONTEND/package-lock.json" -nt "$FRONTEND/node_modules" ]; then
  say "Instaluję zależności frontendu (npm ci)"
  (cd "$FRONTEND" && npm ci --no-audit --no-fund)
fi

# --- start -------------------------------------------------------------------
PIDS=()
kill_tree() {  # pid — stop a process and all its descendants (npx -> sh -> node)
  local child
  for child in $(pgrep -P "$1" 2>/dev/null); do kill_tree "$child"; done
  kill "$1" 2>/dev/null || true
}
cleanup() {
  trap - EXIT INT TERM
  say "Zatrzymuję backend i frontend"
  for pid in "${PIDS[@]}"; do kill_tree "$pid"; done
  wait 2>/dev/null || true
}
trap cleanup EXIT
trap 'cleanup; exit 0' INT TERM

# The backend imports "backend.app..." and "optimizer...", so it runs from the repo root.
say "Start backendu  → http://127.0.0.1:$BACKEND_PORT/docs   (log: .run/backend.log)"
(cd "$ROOT" && exec "$VENV/bin/uvicorn" backend.app.main:app --host 127.0.0.1 --port $BACKEND_PORT) \
  > "$LOGS/backend.log" 2>&1 &
PIDS+=($!)

say "Start frontendu → http://127.0.0.1:$FRONTEND_PORT/      (log: .run/frontend.log)"
(cd "$FRONTEND" && exec npx vite --host 127.0.0.1 --port $FRONTEND_PORT --strictPort) \
  > "$LOGS/frontend.log" 2>&1 &
PIDS+=($!)

wait_for() {  # url logname
  for _ in $(seq 1 60); do
    curl -s -o /dev/null -m 1 "$1" && return 0
    sleep 0.5
  done
  die "$2 nie wystartował — zobacz $LOGS/$2.log"
}
wait_for "http://127.0.0.1:$BACKEND_PORT/api/health" backend
wait_for "http://127.0.0.1:$FRONTEND_PORT/" frontend

URL="http://127.0.0.1:$FRONTEND_PORT/"
say "Gotowe: $URL   (API: http://127.0.0.1:$BACKEND_PORT/docs; Ctrl+C kończy)"
if [ -z "${NO_OPEN:-}" ]; then
  (xdg-open "$URL" >/dev/null 2>&1 || true) &
fi

wait -n "${PIDS[@]}" || true
die "Jeden z procesów się zakończył — zobacz logi w $LOGS/"
