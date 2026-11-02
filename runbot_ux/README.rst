=========
Runbot UX
=========

Personalizaciones de Adhoc sobre Runbot: selección dinámica de módulos a
testear, manejo seguro del addons path y réplica en los builds de la política de
auto-instalación de las bases cliente.

Características
===============

- **Selección dinámica de** ``--test-tags``: al correr tests, deriva los tags a
  partir de patrones definidos por repo (campo *Modules to test*). Soporta
  comodines ``fnmatch`` (``sale,account_*``) y exclusiones con ``-``
  (``-*,sale``).
- **Addons path seguro**: omite paths inexistentes o no válidos (repos vacíos de
  versiones nuevas / OCA) para que Odoo levante igual.
- **Política de auto-instalación por versión**: los builds auto-instalan los
  mismos módulos que las bases cliente, según ``force_auto_install`` de
  ``adhoc.module.module`` en el provider. Un cron diario sincroniza las listas
  por versión y se inyectan en el ``.odoorc`` de cada build.
- **Código en builds vivos solo desde IPs de confianza**: nginx bloquea crear o
  editar acciones de servidor, crons, automatizaciones y campos, e importar
  módulos, salvo desde las IPs del parámetro ``runbot_ux.trusted_ips``. Un
  usuario interno suma su IP hasta la medianoche desde *Test server actions*
  (``/runbot/trusted_ip``), en el menú de usuario; un cron las borra cada día.
- **Triggers nightly y weekly**: un cron diario y uno semanal crean un batch de
  esa categoría en cada bundle base que tenga un trigger de la categoría para
  su versión.
- **Chequeo de licencias**: desde la versión 20.0, el step ``license-check`` revisa los módulos
  instalables de los repos del trigger y falla el build cuando:

  - un módulo de un repo público depende, directa o indirectamente, de un
    módulo ``OEEL-1`` o de un módulo de un repo privado;
  - un módulo ``AGPL-3`` depende, directa o indirectamente, de un módulo
    ``OEEL-1``.

  Cada error dice la cadena de dependencias y cómo corregirlo.

Configuración
=============

La feature de auto-instalación requiere:

- **Endpoint del provider**: ``/saas_provider/get_runbot_auto_install_data`` en
  ``saas_provider_adhoc`` (devuelve, por versión, las listas derivadas de
  ``force_auto_install``).
- **System parameters** en el runbot:

  - ``runbot_ux.provider_url``: URL base del provider.
  - ``runbot_ux.provider_token``: mismo valor que
    ``saas_provider.odoo_project_token`` del provider.

- **server_wide_modules**: el *default odoorc* de los builds debe incluir
  ``saas_client`` (ej. ``server_wide_modules = base,web,saas_client``), para que
  su patch de ``load_manifest`` esté activo al arrancar y aplique las claves
  inyectadas.

Sin los system parameters el cron loguea una advertencia y no sincroniza; sin
``saas_client`` cargado server-wide las claves inyectadas no tienen efecto.

Uso
===

- **Tests por módulo**: setear *Modules to test* en el repo (patrones). Vacío =
  todos los módulos; para desactivar la inyección, desmarcar *Test Enable* en el
  config step.
- **Auto-instalación**: se marca ``force_auto_install`` en
  ``adhoc.module.module`` (provider); el cron diario trae las listas y cada build
  las aplica automáticamente. Las listas sincronizadas se ven en la lista de
  *Versions* (columnas opcionales).
- **Chequeo de licencias**: sumar el step ``license-check`` a la config del
  build, y marcar *Private* en el formulario de cada repo privado. Se marca a
  mano: si un repo cambia de visibilidad en GitHub, hay que cambiarlo ahí.
  *Skip Private Dependency Check* apaga la primera regla para un repo público,
  para las excepciones acordadas o hasta que se corrijan sus módulos. La regla
  de ``AGPL-3`` sigue valiendo.

Dependencias
============

- ``runbot``

Autor
=====

ADHOC SA

Licencia
========

AGPL-3
