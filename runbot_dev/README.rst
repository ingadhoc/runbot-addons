==========
Runbot Dev
==========

Entorno de runbot local para desarrollo. Crea un proyecto de juguete con dos
repos, su propio config de build y el host local, para correr builds de verdad
en segundos sin depender del runbot productivo.

Es un módulo **solo de desarrollo**: todo vive en datos demo y no se instala en
el runbot productivo.

Qué crea
========

Al instalar con datos demo:

- **Host** ``runbot-local``, con ``is_leader`` y ``is_builder`` en ``True``.
- **Proyecto** ``Odoo by Adhoc (dev)``, con tres repos: ``adhoc-cicd-odoo-odoo``
  y ``adhoc-cicd-odoo-enterprise`` (las fuentes, sólo como dependencias) e
  ``ingadhoc-dev`` (los módulos de fixture, el que dispara los builds). Los tres
  se llaman igual que en el runbot productivo.
- **Config** ``[18.0] Odoo by Adhoc Config (with tests)`` con un step
  ``18-all-with-tests`` que instala ``-*,module_*,web_enterprise`` con tests. El
  step ``all`` que shipea runbot instala *todos* los módulos disponibles, que
  acá sería todo odoo más todo enterprise.
- **Trigger** ``[18.0] All`` sin ``ci_context``, así no intenta reportar a
  GitHub.
- **Bundle base** ``18.0``. La ``runbot.version`` la crea runbot sola a partir
  del nombre.
- **Los remotes en disco**, bajo ``<data_dir>/runbot-dev/remotes/``. Son lo que
  en producción es GitHub, y cada uno se llama igual que el ``runbot.repo`` que
  fetchea de él:

  - ``adhoc-cicd-odoo-odoo.git``: un snapshot de las fuentes de odoo con las que
    arranca el server, en un solo commit sobre la rama ``18.0``. Tarda ~20s y
    pesa ~400 MB.
  - ``adhoc-cicd-odoo-enterprise.git``: lo mismo con las fuentes de enterprise,
    que se buscan como hermano del directorio de odoo (overridable con el
    parámetro ``runbot_dev.enterprise_path``). Hace falta para instalar
    ``web_enterprise``, que es lo que acerca el build al aspecto de producción.
  - ``ingadhoc-dev.git`` más un clon de trabajo al lado (``ingadhoc-dev/``), con
    la rama base ``18.0`` y una rama ``18.0-t-99999-dev`` para que haya un
    bundle que buildear. En ese clon commiteás para disparar builds.

- **Saca la capa de chrome** del ``DockerDefault``.

Los nombres siguen los del runbot productivo a propósito, para que la analogía
sea directa: el proyecto, los dos repos, el step y el config se llaman igual que
allá, con ``(dev)`` en el proyecto para que nadie los confunda. No hay nada de
clientes ni el dominio productivo.

Los 4 módulos de ``fixture_modules/`` se llaman ``module_a`` … ``module_d``:
nombres genéricos a propósito, para que se lea de una que son stand-ins y no
módulos reales. Cada uno tiene un test ``post_install`` de duración conocida:

=============  ==========
módulo         duración
=============  ==========
``module_a``   10s
``module_b``   6s
``module_c``   3s
``module_d``   2s
=============  ==========

**21 segundos en serie**, que es la referencia para medir cualquier
paralelización. La convención idiomática de Odoo para módulos que sólo existen
para testear es ``test_*``, pero está descartada: hay 18 módulos ``test_*`` en
``odoo/addons``, así que un patrón ``-*,test_*`` se los instalaría todos.

Todo lo que crea vive bajo un solo directorio::

    <data_dir>/runbot-dev/
    ├── odoo-runbot/          el clon del core (adentro está el módulo runbot)
    ├── pgdata/  pgsocket/    el postgres de este runbot
    ├── builder.log  pg.log
    └── remotes/              "el GitHub" de este runbot
        ├── adhoc-cicd-odoo-odoo.git
        ├── adhoc-cicd-odoo-enterprise.git
        ├── ingadhoc-dev.git
        └── ingadhoc-dev/     clon de trabajo, acá commiteás

La raíz se llama ``runbot-dev`` y no ``runbot`` a propósito: adentro ya hay un
clon ``odoo-runbot`` que contiene un módulo ``runbot``, y tres niveles con el
mismo nombre no ayudan a nadie.

Requisitos
==========

- **Deps de python del runbot**, instaladas **sin los pins** de su
  ``requirements.txt``::

      pip install matplotlib docker unidiff

  Los pins piden ``matplotlib==3.6.3`` y ``numpy==1.26.4``; si el venv tiene
  numpy 2.x, respetarlos lo baja de versión y rompe otras cosas.
- **nginx**, en ``/usr/sbin/nginx``. Cada vuelta del loop llama a
  ``_reload_nginx()``, y si el binario no está la excepción corta la vuelta::

      sudo apt-get install -y nginx-light

- **El daemon de docker accesible** desde donde corre el builder. Los builds
  corren en un container.
- **git >= 2.48**, o el parche que aplica el setup (ver abajo). runbot exporta
  las fuentes con ``git archive --mtime``, opción que no existe antes de 2.48.
- **El core de runbot clonado y en el** ``addons_path``: el directorio que
  contiene ``runbot/``, no ``runbot/`` mismo.
- **Las fuentes de odoo con** ``odoo-bin``, y las de **enterprise** como
  directorio hermano. No hace falta que sean repos git: los snapshots se arman
  del working tree. Sin enterprise el setup avisa y sigue, pero el repo queda
  sin nada que fetchear y los batches reportan un commit faltante.

Paso a paso
===========

Un comando, idempotente, que se puede correr de nuevo cuantas veces haga falta::

    repositories/runbot-addons/runbot_dev/dev_bin/setup.sh

Deja la base, el postgres, el core alineado y el builder corriendo, e imprime
al final el comando para levantar el frontend. Cada paso dice ``ok`` o ``skip``,
así que se ve qué hizo y qué ya estaba.

Lo que hace, y por qué cada cosa:

1. **Descubre** el path del volumen ``/home/odoo/data`` en el host, leyendo
   ``/proc/self/mountinfo``. No hay nada hardcodeado de esta máquina.
2. **Deps de python y nginx**, si faltan.
3. **Alinea los paths.** runbot bind-montea paths absolutos en los containers de
   build, pero el daemon es el del host y el filesystem de este container es su
   propio overlay: los paths de ``_root()`` no existen del otro lado y docker
   los crea vacíos. El script symlinkea el path del host al volumen, así queda
   uno que resuelve al mismo contenido de los dos lados. ``mount --bind`` sería
   más limpio pero necesita ``CAP_SYS_ADMIN``, que el devcontainer no tiene.
4. **Copia el core** al path alineado. Copia y no ``git clone``, porque los
   clones del container son parciales (filtro ``blob:none``) y no pueden servir
   objetos por ``upload-pack``. Efecto lateral bueno: queda en el volumen y
   sobrevive a que recreen el container.
5. **Parcha dos líneas del core copiado.** En ``container.py``, el origen del
   mount del socket de postgres: el container de build corre con
   ``network_mode='none'`` y su única vía a postgres es el socket unix que
   runbot le monta desde ``/var/run/postgresql`` del host, que acá no existe. El
   parche apunta el origen al socket alineado y deja el destino igual, así que
   el build se conecta exactamente como en producción. Y en ``commit.py``, el
   ``--mtime`` del ``git archive`` (ver abajo). Los dos parches son idempotentes
   y avisan si no encuentran qué parchar.
6. **Postgres local**, con el socket en el directorio alineado y el ``PGDATA``
   en el volumen. No usa el postgres compartido del container ``db`` porque su
   socket no es alcanzable desde el host.
7. **Crea la base** e instala ``runbot_dev`` con sus datos demo.
8. **Arranca el builder** con el path alineado primero en el ``addons-path``
   —odoo devuelve la primera coincidencia, y de eso depende que ``_root()`` sea
   el alineado— y con el nombre de host que declaran los datos demo, que es el
   único lugar donde vive.

Para disparar un build hace falta un **cambio real de árbol**. El fingerprint de
``runbot.build.params`` se calcula sobre los ``tree_hash``, no sobre los shas,
así que un ``--allow-empty`` crea el batch pero engancha el build viejo con
``link_type = matched``::

    cd <data_dir>/runbot-dev/remotes/ingadhoc-dev
    date -u > TRIGGER && git add TRIGGER
    git commit -m "probar" && git push origin 18.0-t-99999-dev

El frontend, en una configuración aparte
========================================

El frontend necesita tres flags que **no** sirven para el trabajo normal, así
que va en su propia configuración de ``launch.json`` en vez de tocar la que ya
usás. En este workspace es ``Python:Odoo (runbot local)``:

- ``--db_host /home/odoo/data/runbot/pgsocket`` — la base vive en el postgres
  que levanta el setup. Un odoo que arranque sin esto se conecta al postgres
  compartido del container ``db``, y si ahí hay otra base ``runbot`` vas a ver
  builds viejos y creer que el rebuild no anda.
- ``--addons-path`` con **el mismo clon que usa el builder, y primero** (odoo
  devuelve la primera coincidencia). Se usa el path alineado para que frontend y
  builder resuelvan ``_root()`` al mismo lugar; el alineado y el real son el
  mismo contenido vía symlink, así que para *servir* sirven los dos. Lo que
  rompe es apuntar a **otro clon** — por ejemplo el de ``/home/odoo/src``, cuyo
  ``static/`` no tiene nada de estos builds.
- ``--load=base,web`` — ese addons-path acotado no tiene ``server_mode`` ni
  ``saas_client``, que el ``odoo.conf`` declara como server wide.

Y en el ``env`` de la configuración, ``PGHOST`` apuntando al socket (ver la nota
de abajo).

Para armarla en otro workspace: copiar la configuración que ya existe, agregarle
esos tres args y el ``PGHOST``, y dejar la original intacta.

Limpieza cuando terminás de usarlo
==================================

**Cerrar el container no alcanza.** Sobreviven unos 2 GB: el árbol
``<data_dir>/runbot-dev`` vive en un volumen de docker (~580 MB) y las imágenes
de build viven en el daemon del host (~1,5 GB). Y las bases de build que quedan
huérfanas pasan desapercibidas: el gc de runbot las ve en cada vuelta y las
deja, loggeando ``not deleted because no corresponding build found``.

Por eso hay un script espejo::

    repositories/runbot-addons/runbot_dev/dev_bin/cleanup.sh

Por default saca lo que es de este entorno: baja el builder y el postgres,
borra el árbol entero, el symlink de alineación y las bases de build huérfanas
—en el postgres local **y en el compartido**, que es donde nadie las busca—.
Más una base ``runbot`` en el compartido si quedó, porque un frontend que
arranque sin ``--db_host`` se conecta a ésa.

Una sola cosa es opt-in: ``--images`` borra también las imágenes de docker.
Reconstruirlas son ~6 minutos y red, así que si vas a volver conviene
conservarlas.

**Los paquetes de apt y pip no se tocan**, porque están en el filesystem del
container y se van con él. Tampoco toca containers de docker: los builds corren
con ``auto_remove=True`` y no dejan ninguno.

Si una base tiene conexiones activas no la borra: avisa y sigue.

Qué sobrevive a recrear el container
====================================

En el volumen (sobreviven): el core, el postgres, los repos de juguete y la
base. En el overlay (se van): las deps de pip, nginx y el symlink de
alineación. Volver a correr el ``setup.sh`` los repone y saltea el resto.

Notas
=====

- ``is_leader`` viene en ``False`` por default en ``runbot.host``, y sin un
  leader no se crea ningún batch. Los datos demo lo dejan en ``True``.
- **El clon local de odoo no sirve como remote.** Es un clon parcial (filtro
  ``blob:none``) y git deshabilita el lazy fetch mientras sirve ``upload-pack``,
  así que el espejo queda con cero refs y los batches reportan *Missing commit*.
  De ahí el snapshot.
- **La capa de chrome del** ``DockerDefault`` **pinnea un** ``.deb`` que Google
  ya no conserva en su pool, así que la imagen nunca termina de construirse. Los
  datos demo la borran; los tests de juguete son ``TransactionCase`` y no usan
  browser. Si hacen falta tours, hay que actualizar la versión en la capa.
- **La imagen tiene que traer los requirements de la versión que se buildea.**
  El ``DockerDefault`` que shipea runbot instala los de ``master``, y odoo 18.0
  todavía necesita paquetes que master dejó de usar (``odoo/tools/cache.py``
  importa ``decorator``). El build corre sin red, así que no puede instalarlos
  él: tienen que venir en la imagen. Los datos demo apuntan la capa
  ``runbot.docker_layer_branch_req`` a ``18.0``. **No** alcanza con
  ``skip_requirements``: el paquete hace falta de verdad, no es una dependencia
  de los módulos que se testean. Después de cambiar la capa hay que dejar que el
  builder reconstruya la imagen.
- **``PGHOST`` es imprescindible para el builder y para el frontend.** runbot
  hace sus operaciones de administración —crear y borrar las bases de cada
  build, listar las bases locales, la base de logs— con
  ``psycopg2.connect("dbname=...")`` **sin host**, o sea por variables de
  entorno. En este container ``PGHOST=db`` apunta al postgres compartido, así
  que sin sobrescribirlo runbot administra bases ahí y no en el suyo. El
  síntoma es feo y no obvio: ``_process_logs`` no encuentra ``runbot_logs``,
  la excepción corta **la vuelta entera del scheduler** antes de asignar
  builds, y los builds nuevos se quedan en ``pending`` para siempre.
- ``web_enterprise`` **está en** ``install_modules`` **de forma explícita**,
  aunque su ``auto_install`` sobre ``web`` ya lo traería solo. Explícito es
  determinista y se lee en el comando del build.
- **``-u`` no sincroniza los datos demo.** odoo los carga siempre con
  ``noupdate=True`` —lo dice el docstring de ``load_data`` en
  ``odoo/modules/loading.py``, sin importar lo que declare el ``<odoo>``—, así
  que los registros que ya existen no se actualizan. Para que un cambio en el
  demo entre hay que **rehacer la base**: ``cleanup.sh`` y después ``setup.sh``.
  El ``-u`` sirve para el código (models, vistas), no para el demo.
- **El** ``--mtime`` **del export.** runbot 18.0 exporta las fuentes con
  ``git archive <tree> --mtime <fecha del commit>``, y ``--mtime`` es de git
  2.48. Ningún Debian estable lo trae: bookworm tiene 2.39 y trixie 2.47, y
  backports no tiene el paquete. Sin resolverlo, todo build muere en el export
  con ``unknown option `mtime'`` antes de instalar nada. El setup saca la
  opción del core copiado; el único efecto es que los archivos exportados
  quedan con la fecha actual en vez de la del commit, y nada en un build los
  mira. El fix real es git >= 2.48 en la imagen del container, y vale saber que
  el host productivo de runbot ya corre uno.
- **Si la imagen falla una vez, no se reintenta.** ``Dockerfile._build`` setea
  ``in_error`` y el loop la saltea mientras siga en ``True``. Después de
  arreglar la causa hay que limpiar el flag a mano en el ``runbot.dockerfile``.
- Los repos usan ``test_modules`` (el campo que agrega ``runbot_ux``) para que
  la inyección dinámica de ``--test-tags`` resuelva sólo los 4 módulos de
  juguete y no los ~800 de odoo.
- Los remotes son paths locales. ``Remote._compute_base_infos`` les saca
  ``s[-3:]`` para adivinar dominio / owner / nombre, así que necesitan al menos
  tres segmentos; lo que sale de ahí es basura cosmética e inofensiva mientras
  ``send_status`` esté apagado y no haya token.
- Los remotes **no se recrean** si ya existen, así que los commits
  locales sobreviven un update del módulo. Para regenerarlos, borrar
  ``<data_dir>/runbot-dev/remotes``. El snapshot del server tampoco se refresca solo: si
  actualizás las fuentes de odoo y querés que el build las use, hay que
  borrarlo.
