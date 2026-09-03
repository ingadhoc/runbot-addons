#!/usr/bin/env bash
# Bring up a working local runbot in an Adhoc 18.0 devcontainer.
# Its mirror is cleanup.sh.
#
# Idempotent: every step checks first and says what it did. Safe to re-run.
#
# The hard part this solves: runbot bind-mounts absolute paths into the build
# containers, but the docker daemon is the HOST's and this container's
# filesystem is its own overlay. So the runbot root has to sit at a path that
# resolves to the same content inside and outside, and postgres has to be
# reachable from a build container that runs with no network at all.
#
# The module README explains the reasoning behind each step.
set -euo pipefail

MODULE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV=/home/odoo/venv
DATA=/home/odoo/data
DB=runbot
PG_VERSION=15
ODOO_SRC=/home/odoo/src/odoo
LOG_CONTAINER=runbot-dev-logs
LOG_PORT=8888
ENTERPRISE_SRC=/home/odoo/src/enterprise

say() { printf '\n\033[1m== %s\033[0m\n' "$1"; }
ok() { printf '   ok    %s\n' "$1"; }
skip() { printf '   skip  %s\n' "$1"; }
die() { printf '\n   ERROR %s\n' "$1" >&2; exit 1; }

# ---------------------------------------------------------------- discovery
say "Descubriendo el entorno"
HOST_DATA="$(awk -v t="$DATA" '$5==t {print $4}' /proc/self/mountinfo | head -1)"
[ -n "$HOST_DATA" ] || die "$DATA no es un mount: no puedo alinear ningun path con el host"
ok "volumen: $DATA  <->  $HOST_DATA (en el host)"

docker info >/dev/null 2>&1 || die "el daemon de docker no responde"
ok "docker: $(docker info --format '{{.Name}} / {{.ServerVersion}}')"

sudo -n true 2>/dev/null || die "hace falta sudo sin password"

[ -f "$ODOO_SRC/odoo-bin" ] || die "no encuentro odoo-bin en $ODOO_SRC"
ok "fuentes de odoo: $ODOO_SRC"
if [ -f "$ENTERPRISE_SRC/web_enterprise/__manifest__.py" ]; then
    ok "fuentes de enterprise: $ENTERPRISE_SRC"
else
    echo "   AVISO no encuentro web_enterprise en $ENTERPRISE_SRC:"
    echo "         el repo adhoc-cicd-odoo-enterprise no va a tener nada que fetchear"
    echo "         y los batches van a reportar un commit faltante."
fi

RUNBOT_ROOT="$DATA/runbot-dev"              # real, visto desde aca
ALIGNED_ROOT="$HOST_DATA/runbot-dev"        # mismo contenido, path que ve el host
CORE="$ALIGNED_ROOT/odoo-runbot"            # el core se referencia SIEMPRE alineado
PGDATA="$RUNBOT_ROOT/pgdata"
PGSOCK="$RUNBOT_ROOT/pgsocket"
PGSOCK_ALIGNED="$ALIGNED_ROOT/pgsocket"
mkdir -p "$RUNBOT_ROOT"

# ---------------------------------------------------------------- python deps
say "Deps de python"
# Without the requirements.txt pins: they ask for matplotlib 3.6.3 + numpy
# 1.26.4, which would downgrade the numpy 2.x of the shared venv.
MISSING=""
for mod in matplotlib docker unidiff; do
    "$VENV/bin/python" -c "import $mod" 2>/dev/null || MISSING="$MISSING $mod"
done
if [ -n "$MISSING" ]; then
    "$VENV/bin/pip" install --no-cache-dir $MISSING >/dev/null
    ok "instalados:$MISSING"
else
    skip "matplotlib, docker y unidiff ya estan"
fi

# ---------------------------------------------------------------- nginx
say "nginx"
# Every loop turn calls _reload_nginx(), and the exception aborts the turn.
if [ -x /usr/sbin/nginx ]; then
    skip "/usr/sbin/nginx ya esta"
else
    sudo apt-get install -y -qq nginx-light >/dev/null
    ok "nginx-light instalado"
fi

# ---------------------------------------------------------------- path alignment
say "Alineacion de paths"
# The core and everything under _root() must live at a path that resolves to
# the same content inside and on the host. mount --bind would be cleaner but
# needs CAP_SYS_ADMIN, which the devcontainer does not have, so: symlink.
if [ "$(readlink -f "$HOST_DATA" 2>/dev/null || true)" = "$DATA" ]; then
    skip "$HOST_DATA ya apunta a $DATA"
else
    # ln -sfn does not replace a real directory: it would put the link inside.
    if [ -d "$HOST_DATA" ] && [ ! -L "$HOST_DATA" ]; then
        sudo rm -rf "$HOST_DATA" 2>/dev/null || die "hay un directorio real en $HOST_DATA que no pude sacar"
        ok "saque el directorio real que habia en $HOST_DATA"
    fi
    sudo mkdir -p "$(dirname "$HOST_DATA")"
    sudo ln -sfn "$DATA" "$HOST_DATA"
    ok "symlink $HOST_DATA -> $DATA"
fi
echo "alineacion" > "$RUNBOT_ROOT/.aligned"
[ -f "$ALIGNED_ROOT/.aligned" ] || die "la alineacion no funciono: $ALIGNED_ROOT no ve el contenido"
rm -f "$RUNBOT_ROOT/.aligned"
ok "verificada: $ALIGNED_ROOT ve el mismo contenido que $RUNBOT_ROOT"

# ---------------------------------------------------------------- core
say "Core de runbot"
if [ -d "$CORE/runbot" ]; then
    skip "ya esta en $CORE"
else
    SRC=""
    for cand in /home/odoo/src/repositories/odoo-runbot /home/odoo/custom/repositories/odoo-runbot; do
        [ -d "$cand/runbot" ] && SRC="$cand" && break
    done
    [ -n "$SRC" ] || die "no encontre un clon de odoo/runbot para copiar; clonalo en $CORE (rama 18.0)"
    # Copy, not git clone: the container's clones are partial (blob:none
    # filter) and cannot serve objects over upload-pack.
    mkdir -p "$CORE"
    cp -a "$SRC/." "$CORE/"
    ok "copiado desde $SRC a $CORE (rama $(git -C "$CORE" branch --show-current))"
fi

# ---------------------------------------------------------------- core patches
# Three things in the runbot core do not work in this container. All of them
# are patched in the copy, so nothing else has to be worked around later.
say "Parches del core"
python3 - "$CORE" "$PGSOCK_ALIGNED" <<'PY'
import sys

core, sock = sys.argv[1], sys.argv[2]

# The build container gets the postgres socket bind-mounted from the host.
# runbot hardcodes /var/run/postgresql as the source and on the host that does
# not exist, so point the source at the aligned socket, target unchanged.
path = core + "/runbot/container.py"
s = open(path).read()
if sock in s:
    print("   skip  container.py ya apunta al socket alineado")
else:
    old = "        '/var/run/postgresql': {'bind': '/var/run/postgresql', 'mode': 'rw'},"
    assert old in s, "no encontre el mount de /var/run/postgresql en container.py"
    new = (
        "        # runbot_dev: the source is the socket aligned with the host,\n"
        "        # because there is no /var/run/postgresql on the host to mount.\n"
        "        '%s': {'bind': '/var/run/postgresql', 'mode': 'rw'}," % sock
    )
    open(path, "w").write(s.replace(old, new, 1))
    print("   ok    container.py: origen del socket -> %s" % sock)

# `git archive --mtime` needs git >= 2.48 and no Debian stable ships it
# (bookworm 2.39, trixie 2.47), so without this every build dies exporting the
# sources with "unknown option `mtime'" before installing anything. Dropping
# the flag only means the exported files carry the current time instead of the
# commit date, and nothing in a build reads them. The real fix is git >= 2.48
# in the container image.
path = core + "/runbot/models/commit.py"
s = open(path).read()
old = ", '--mtime', self.date.strftime('%Y-%m-%d %H:%M:%S')"
if old not in s:
    print("   skip  commit.py ya exporta sin --mtime")
else:
    open(path, "w").write(s.replace(old, "", 1))
    print("   ok    commit.py: git archive sin --mtime")

# The urls of the build logs have two readers: the browser, and the wget of a
# child build restoring the dump of its parent. A build container cannot reach
# this devcontainer, so those urls point at a sidecar that serves the same
# files on a port of the host. The name of the runbot.host is left alone, so
# the frontend keeps answering where it did. runbot.use_ssl is no help here
# either: get_param returns `value or default`, so it cannot be turned off.
path = core + "/runbot/models/build.py"
s = open(path).read()
old = """        use_ssl = self.env['ir.config_parameter'].get_param('runbot.use_ssl', default=True)
        return '%s://%s/runbot/static/build/%s/logs/' % ('https' if use_ssl else 'http', self.host, self.dest)"""
new = """        # runbot_dev: ver dev_bin/setup.sh
        base = self.env['ir.config_parameter'].sudo().get_param('runbot_dev.log_url_base') or 'http://%s' % self.host
        return '%s/runbot/static/build/%s/logs/' % (base.rstrip('/'), self.dest)"""
if "runbot_dev.log_url_base" in s:
    print("   skip  build.py ya arma las urls con la base del sidecar")
else:
    assert old in s, "no encontre _http_log_url en build.py"
    open(path, "w").write(s.replace(old, new, 1))
    print("   ok    build.py: urls de logs por runbot_dev.log_url_base")
PY

# ---------------------------------------------------------------- postgres
say "Postgres local"
# The build container runs with network_mode='none': its only way to postgres
# is the mounted unix socket. Hence a postgres here, with its socket in the
# aligned directory.
if [ ! -x "/usr/lib/postgresql/$PG_VERSION/bin/postgres" ]; then
    sudo apt-get install -y -qq "postgresql-$PG_VERSION" >/dev/null
    ok "postgresql-$PG_VERSION instalado"
else
    skip "postgresql-$PG_VERSION ya esta"
fi

mkdir -p "$PGSOCK"
if [ -f "$PGDATA/PG_VERSION" ]; then
    skip "cluster ya inicializado en $PGDATA"
else
    mkdir -p "$PGDATA"
    "/usr/lib/postgresql/$PG_VERSION/bin/initdb" -D "$PGDATA" -U odoo -A trust >/dev/null
    ok "cluster inicializado en $PGDATA (owner odoo, auth trust)"
fi

if "/usr/lib/postgresql/$PG_VERSION/bin/pg_ctl" -D "$PGDATA" status >/dev/null 2>&1; then
    skip "postgres ya corriendo"
else
    "/usr/lib/postgresql/$PG_VERSION/bin/pg_ctl" -D "$PGDATA" -l "$RUNBOT_ROOT/pg.log" \
        -o "-k $PGSOCK -c listen_addresses=" start >/dev/null
    ok "postgres arrancado (socket en $PGSOCK)"
fi
psql -h "$PGSOCK" -d postgres -tAc "select 1" >/dev/null || die "no puedo conectar al postgres local"
ok "conexion ok: $(psql -h "$PGSOCK" -d postgres -tAc 'show server_version')"

# ---------------------------------------------------------------- log sidecar
say "Sidecar de logs"
# A build container runs on the docker host, on another bridge, and neither
# reaches this devcontainer nor resolves its name. What it does reach is the
# gateway of its own bridge, so the logs are served there: it is the only way a
# child build can download the dump of its parent.
GATEWAY="$(docker network inspect bridge -f '{{(index .IPAM.Config 0).Gateway}}' 2>/dev/null)"
[ -n "$GATEWAY" ] || die "no pude averiguar el gateway de la bridge de docker"
LOG_URL_BASE="http://$GATEWAY:$LOG_PORT"
if [ "$(docker inspect -f '{{.State.Running}}' "$LOG_CONTAINER" 2>/dev/null)" = "true" ]; then
    skip "$LOG_CONTAINER ya corriendo en $LOG_URL_BASE"
else
    docker rm -f "$LOG_CONTAINER" >/dev/null 2>&1
    docker run -d --name "$LOG_CONTAINER" --restart unless-stopped -p "$LOG_PORT:80" \
        -v "$CORE/runbot/static:/usr/share/nginx/html/runbot/static:ro" nginx:alpine >/dev/null \
        || die "no pude levantar el sidecar de logs"
    ok "$LOG_CONTAINER levantado en $LOG_URL_BASE"
fi

# ---------------------------------------------------------------- database
say "Base $DB"
# ENTERPRISE_SRC goes in the addons-path so web_enterprise gets installed in
# the local runbot: its auto_install on web brings it in on its own, with no
# depends to declare.
ADDONS="$CORE,$(dirname "$MODULE_DIR"),$ODOO_SRC/addons,$ODOO_SRC/odoo/addons,$ENTERPRISE_SRC"
if psql -h "$PGSOCK" -lqt | cut -d'|' -f1 | tr -d ' ' | grep -qx "$DB"; then
    skip "la base $DB ya existe (borrala para rehacerla de cero)"
else
    "$VENV/bin/odoo" -d "$DB" -i runbot_dev --stop-after-init --no-http \
        --addons-path "$ADDONS" --load=base,web --db_host "$PGSOCK" --log-level=warn >/dev/null
    ok "base creada con runbot_dev y sus datos demo"
fi

# ---------------------------------------------------------------- builder
# The demo data is the only place that names the runbot.host, and the builder
# has to be told the same name: it resolves its host by this flag, while the
# server resolves it by fqdn(). The name also has to resolve from the browser,
# because runbot builds the log links as <scheme>://<host>/runbot/static/...
psql -h "$PGSOCK" -d "$DB" -tAc "insert into ir_config_parameter (key, value) values ('runbot_dev.log_url_base', '$LOG_URL_BASE') on conflict (key) do update set value = excluded.value" >/dev/null
ok "urls de logs contra $LOG_URL_BASE"

HOST_NAME="$(psql -h "$PGSOCK" -d "$DB" -tAc "select name from runbot_host limit 1")"
[ -n "$HOST_NAME" ] || die "no hay ningun runbot.host en la base $DB"

say "Builder"
# ps + grep instead of pgrep -f: the pattern shows up in this script's own
# command line and would match itself.
if ps -eo args | grep -q "^[^ ]*python main\.py --odoo-path.* -d $DB"; then
    skip "ya hay un builder corriendo"
else
    cd "$CORE/runbot_builder"
    # PGHOST is not optional: runbot does its admin work (creating and
    # dropping build databases, listing local ones, the logs database) with
    # psycopg2.connect("dbname=...") with no host, i.e. through libpq env
    # vars. Without this they go to the shared postgres of the db container
    # instead of this runbot's, and _process_logs aborts the whole
    # scheduler turn.
    PGHOST="$PGSOCK" \
    nohup "$VENV/bin/python" main.py \
        --odoo-path "$ODOO_SRC" \
        --addons-path "$ADDONS" \
        --db_host "$PGSOCK" \
        -d "$DB" --forced-host-name "$HOST_NAME" \
        > "$RUNBOT_ROOT/builder.log" 2>&1 &
    ok "builder arrancado, log en $RUNBOT_ROOT/builder.log"
fi

# Warn: a $DB database in the shared postgres is confusing, because a
# frontend started without --db_host connects to that one instead of this
# runbot's.
if psql -h db -lqt 2>/dev/null | cut -d'|' -f1 | tr -d ' ' | grep -qx "$DB"; then
    say "OJO"
    echo "   Hay otra base \"$DB\" en el postgres compartido (host db). Un odoo que"
    echo "   arranque sin --db_host se conecta a ESA, no a la de este runbot, y vas a"
    echo "   ver builds viejos. Borrala cuando puedas: dropdb -h db $DB"
fi

say "Listo"
cat <<EOF
   base:     $DB en $PGSOCK
   core:     $CORE
   log:      $RUNBOT_ROOT/builder.log

   host:     $HOST_NAME  (el frontend responde contra este nombre)
   logs:     $LOG_URL_BASE  (los alcanzan el navegador y los build containers)

   frontend (con --db_host y el core alineado primero, los dos hacen falta):
     $VENV/bin/odoo -d $DB --addons-path "$ADDONS" --load=base,web --db_host $PGSOCK
   Agregale --http-port 8169 si ya tenes otro odoo en el 8069; si queres entrar
   por la URL de traefik, baja el otro y dejalo en el puerto por default.

   Para disparar un build hace falta un cambio real de arbol (el fingerprint va
   sobre el tree_hash, no sobre el sha):
       cd $RUNBOT_ROOT/remotes/ingadhoc-dev
       date -u > TRIGGER && git add TRIGGER && git commit -m probar && git push origin 18.0-t-99999-dev
EOF
