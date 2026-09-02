#!/usr/bin/env bash
# Undo what setup.sh created. Its mirror.
#
# It removes what this environment owns: the builder and postgres processes,
# the whole <data_dir>/runbot-dev tree, the alignment symlink, and the orphaned
# build databases. Only the docker images are opt-in, with --images, because
# they are expensive to rebuild.
#
# Nothing here touches the apt or pip packages that setup.sh installs: they live
# in the container filesystem and go away with it.
set -uo pipefail

MODULE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA=/home/odoo/data
DB=runbot
PG_VERSION=15
BUILD_DB_RE='^[0-9]{5}-'  # runbot names them <build id>-<version>-...

WITH_IMAGES=0
for arg in "$@"; do
    case "$arg" in
        --images) WITH_IMAGES=1 ;;
        -h|--help)
            cat <<'AYUDA'
cleanup.sh - deshace lo que dejó setup.sh

Saca lo que es de este entorno: baja el builder y el postgres, borra el árbol
<data_dir>/runbot-dev, el symlink de alineación y las bases de build huérfanas
(en el postgres local y en el compartido).

  --images   borra además las imágenes de docker (~1,5 GB; reconstruirlas son
             ~6 min y red). Salteálo si vas a volver.

Los paquetes de apt y pip que instala setup.sh no se tocan: se van solos al
recrear el container. Una base con conexiones activas no se borra: avisa y
sigue.
AYUDA
            exit 0 ;;
        *) echo "Opción desconocida: $arg (probá --help)" >&2; exit 1 ;;
    esac
done

say() { printf '\n\033[1m== %s\033[0m\n' "$1"; }
ok() { printf '   ok    %s\n' "$1"; }
skip() { printf '   skip  %s\n' "$1"; }

RUNBOT_ROOT="$DATA/runbot-dev"
PGDATA="$RUNBOT_ROOT/pgdata"
PGSOCK="$RUNBOT_ROOT/pgsocket"
HOST_DATA="$(awk -v t="$DATA" '$5==t {print $4}' /proc/self/mountinfo | head -1)"

FREED_BEFORE="$(du -sm "$RUNBOT_ROOT" 2>/dev/null | cut -f1)"

# ------------------------------------------------------------------ processes
say "Procesos"
# ps + grep instead of pgrep -f: the pattern shows up in this script's own
# command line and would match itself.
PIDS="$(ps -eo pid,args | grep "^ *[0-9]* [^ ]*python main\.py --odoo-path" | awk '{print $1}')"
if [ -n "$PIDS" ]; then
    for p in $PIDS; do kill "$p" 2>/dev/null && ok "builder $p bajado"; done
    sleep 3
    ps -eo args | grep -q "^[^ ]*python main\.py --odoo-path" \
        && echo "   AVISO el builder sigue vivo, mirá con: ps -eo pid,args | grep main.py" \
        || true
else
    skip "no había builder corriendo"
fi

# ------------------------------------------------------------------ orphaned databases
# These are the ones that go unnoticed: runbot's own gc leaves them behind,
# logging "not deleted because no corresponding build found" every turn.
say "Bases de build huérfanas"
drop_orphans() {
    local host="$1" label="$2" found=0
    psql -h "$host" -d postgres -tAc "select 1" >/dev/null 2>&1 || { skip "$label no responde"; return; }
    for d in $(psql -h "$host" -d postgres -tAc "select datname from pg_database where datname ~ '$BUILD_DB_RE'" 2>/dev/null); do
        found=1
        local conns
        conns="$(psql -h "$host" -d postgres -tAc "select count(*) from pg_stat_activity where datname='$d'" 2>/dev/null || echo 0)"
        if [ "${conns:-0}" -gt 0 ]; then
            echo "   AVISO $d tiene $conns conexiones, no la borro"
            continue
        fi
        local size
        size="$(psql -h "$host" -d postgres -tAc "select pg_size_pretty(pg_database_size('$d'))" 2>/dev/null)"
        dropdb -h "$host" "$d" 2>/dev/null && ok "$label: $d ($size)"
    done
    [ "$found" = 0 ] && skip "$label: ninguna"
    return 0
}
# The shared postgres first: those survive even recreating the container.
drop_orphans db "postgres compartido"
# The local one only if it is still up; otherwise it goes with the directory.
if "/usr/lib/postgresql/$PG_VERSION/bin/pg_ctl" -D "$PGDATA" status >/dev/null 2>&1; then
    drop_orphans "$PGSOCK" "postgres local"
fi

# ------------------------------------------------------------------ postgres
say "Postgres local"
if "/usr/lib/postgresql/$PG_VERSION/bin/pg_ctl" -D "$PGDATA" status >/dev/null 2>&1; then
    "/usr/lib/postgresql/$PG_VERSION/bin/pg_ctl" -D "$PGDATA" stop -m fast >/dev/null 2>&1 \
        && ok "detenido" || echo "   AVISO no pude detenerlo"
else
    skip "no estaba corriendo"
fi

# A $DB database in the shared postgres is a frequent leftover, and it is
# actively confusing: a frontend started without --db_host connects to it.
if psql -h db -lqt 2>/dev/null | cut -d'|' -f1 | tr -d ' ' | grep -qx "$DB"; then
    if [ "$(psql -h db -d postgres -tAc "select count(*) from pg_stat_activity where datname='$DB'" 2>/dev/null || echo 0)" -gt 0 ]; then
        echo "   AVISO hay una base \"$DB\" en el postgres compartido y está en uso; bajá el odoo que la tiene y corré: dropdb -h db $DB"
    else
        dropdb -h db "$DB" && ok "base \"$DB\" del postgres compartido borrada"
    fi
fi

# ------------------------------------------------------------------ data
say "Datos"
if [ -d "$RUNBOT_ROOT" ]; then
    rm -rf "$RUNBOT_ROOT" && ok "$RUNBOT_ROOT borrado (${FREED_BEFORE:-?} MB)"
else
    skip "$RUNBOT_ROOT no existe"
fi

if [ -n "$HOST_DATA" ] && [ -L "$HOST_DATA" ]; then
    sudo rm -f "$HOST_DATA" && ok "symlink de alineación borrado"
else
    skip "no había symlink de alineación"
fi

# ------------------------------------------------------------------ docker
say "Docker"
# Only the images: the build containers run with auto_remove=True, so runbot
# never leaves any behind.
if [ "$WITH_IMAGES" = 1 ]; then
    for tag in odoo:DockerDefault odoo:DockerDefault.future; do
        docker image inspect "$tag" >/dev/null 2>&1 \
            && docker rmi "$tag" >/dev/null 2>&1 && ok "imagen $tag borrada"
    done
else
    IMGS="$(docker images --format '{{.Repository}}:{{.Tag}} {{.Size}}' 2>/dev/null | grep '^odoo:Docker' || true)"
    if [ -n "$IMGS" ]; then
        skip "imágenes conservadas (--images para borrarlas):"
        echo "$IMGS" | sed 's/^/           /'
    fi
fi

say "Listo"
echo "   Para volver a levantarlo: $MODULE_DIR/dev_bin/setup.sh"
