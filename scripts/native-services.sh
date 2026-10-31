#!/usr/bin/env bash
# Start PostgreSQL 16 + Mailpit WITHOUT Docker or sudo (what the prototype was developed with).
# PostgreSQL binaries come from the `pgserver` Python wheel; Mailpit is the official release binary.
#   scripts/native-services.sh start | stop | status
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VAR="$ROOT/var/native"
PGPORT="${PGPORT:-55432}"
MAILPIT_VERSION="v1.33.0"
mkdir -p "$VAR"

pgbin() {
  if [ ! -x "$VAR/pgenv/bin/python" ]; then
    python3 -m venv "$VAR/pgenv" && "$VAR/pgenv/bin/pip" -q install "pgserver==0.1.4"
  fi
  echo "$("$VAR/pgenv/bin/python" -c 'import pgserver,os;print(os.path.dirname(pgserver.__file__))')/pginstall/bin"
}

start() {
  B="$(pgbin)"
  if [ ! -d "$VAR/pgdata" ]; then
    "$B/initdb" -D "$VAR/pgdata" -U postgres --auth=trust -E UTF8 >/dev/null
  fi
  # TCP only (avoids unix-socket path-length limits); listens on localhost.
  "$B/pg_ctl" -D "$VAR/pgdata" -o "-p $PGPORT -k ''" -l "$VAR/pg.log" status >/dev/null 2>&1 \
    || "$B/pg_ctl" -D "$VAR/pgdata" -o "-p $PGPORT -k ''" -l "$VAR/pg.log" start
  for db in talent talent_test talent_volume; do
    "$B/psql" -h localhost -p "$PGPORT" -U postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$db'" | grep -q 1 \
      || "$B/psql" -h localhost -p "$PGPORT" -U postgres -c "CREATE DATABASE $db" >/dev/null
  done
  if [ ! -x "$VAR/mailpit" ]; then
    curl -sSL "https://github.com/axllent/mailpit/releases/download/$MAILPIT_VERSION/mailpit-linux-amd64.tar.gz" \
      | tar xz -C "$VAR" mailpit
  fi
  if ! pgrep -f "$VAR/mailpit" >/dev/null; then
    nohup "$VAR/mailpit" --smtp 127.0.0.1:1025 --listen 127.0.0.1:8025 >"$VAR/mailpit.log" 2>&1 &
  fi
  echo "PostgreSQL: postgresql+psycopg://postgres@localhost:$PGPORT/talent   Mailpit: http://localhost:8025"
}

stop() {
  B="$(pgbin)"
  "$B/pg_ctl" -D "$VAR/pgdata" stop || true
  pkill -f "$VAR/mailpit" || true
}

case "${1:-start}" in
  start) start ;;
  stop) stop ;;
  status) B="$(pgbin)"; "$B/pg_ctl" -D "$VAR/pgdata" status || true; pgrep -fa "$VAR/mailpit" || echo "mailpit not running" ;;
  *) echo "usage: $0 start|stop|status"; exit 1 ;;
esac
