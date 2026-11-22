#!/bin/sh
set -eu
cd "$(dirname "$0")/mcod"
dc() { docker compose --env-file ../../.raed-lokalne/mcod.env -p aed2 -f docker-compose.local.yml -f compose.aed.yml "$@"; }
mkdir -p ../../.raed-lokalne/media ../../.raed-lokalne/wk ../../.raed-lokalne/test-data
if [ ! -f ../../.raed-lokalne/mcod.env ]; then
    python3 -c 'from pathlib import Path; import re,secrets; p=Path("env.sample").read_text(); Path("../../.raed-lokalne/mcod.env").write_text(re.sub(r"(?m)^FIELD_ENCRYPTION_KEYS=.*$", "FIELD_ENCRYPTION_KEYS="+secrets.token_hex(32),p))'
fi
mkdir -p ../../.raed-lokalne/dane/cache
for sample in ../data/cache/*.json; do
    name=$(basename "$sample")
    if [ ! -f "../../.raed-lokalne/dane/cache/$name" ]; then cp "$sample" "../../.raed-lokalne/dane/cache/$name"; fi
done
export DISCOURSE_FORUM_ENABLED=false
if [ "${AED_REBUILD:-0}" = 1 ] || ! docker image inspect aed2-mcod:local >/dev/null 2>&1; then
    dc build mcod-local-admin mcod-nginx mcod-db mcod-rabbitmq mcod-redis mcod-elasticsearch mcod-rdfdb
fi
dc up -d mcod-db mcod-rabbitmq mcod-redis mcod-elasticsearch mcod-rdfdb mcod-smtp
ready() {
    attempts=0
    until "$@" >/dev/null 2>&1; do
        attempts=$((attempts+1))
        [ "$attempts" -lt 90 ] || { echo "Usługa jeszcze nie odpowiada: $*" >&2; return 1; }
        sleep 2
    done
}
ready dc exec -T mcod-db pg_isready -U mcod
ready dc exec -T mcod-elasticsearch curl -fsS localhost:9200
ready dc exec -T mcod-rabbitmq rabbitmq-diagnostics -q ping
# Stan inicjalizacji jest zapisany w bazie.
dc exec -T mcod-db psql -U mcod -d mcod -c "CREATE TABLE IF NOT EXISTS aed_demo_steps (step text PRIMARY KEY)"
done_step() {
    dc exec -T mcod-db psql -U mcod -d mcod -Atc "SELECT COUNT(*) FROM aed_demo_steps WHERE step='$1'" | grep -qx 1
}
mark_step() {
    dc exec -T mcod-db psql -U mcod -d mcod -c "INSERT INTO aed_demo_steps VALUES ('$1') ON CONFLICT DO NOTHING"
}
if ! done_step fixtures; then
    dc run --rm --no-deps inicjalizacja python manage.py init_aed_demo
    mark_step fixtures
fi
if ! done_step indexes; then
    dc run --rm --no-deps inicjalizacja python manage.py search_index --rebuild -f
    mark_step indexes
fi
dc run --rm --no-deps inicjalizacja python manage.py migrate
dc up -d mcod-local-admin mcod-local-api mcod-local-cms mcod-local-celery rejestr
if ! done_step dostawcy_aed_v2; then
    dc exec -T rejestr python manage.py publikuj_aed --demo
    mark_step dostawcy_aed_v2
else
    dc exec -T rejestr python manage.py publikuj_aed
fi
dc up -d synchronizacja
dc exec -T rejestr python -m integracja.sprawdz || echo "UWAGA: autotest integracji zgłosił błąd (szczegóły wyżej). Portal i rejestr działają dalej." >&2
printf '%s\n' 'Portal https://mcod.local/pl  |  Rejestr https://mcod.local/  |  Redakcja https://admin.mcod.local/'

