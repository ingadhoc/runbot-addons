=====================
Runbot Attach VS Code
=====================

Bakes `code-server <https://github.com/coder/code-server>`_ (VS Code in
the browser) plus a curated set of AI coding CLIs (Claude Code, OpenAI
Codex, Google Gemini, OpenCode) into runbot Dockerfiles via a reusable
``runbot.docker_layer``. Each wakeable ``runbot.build`` whose Dockerfile
attaches that layer exposes an *Open VS Code* button that opens, **per
user**, a dedicated code-server side container attached to the build —
with the AI CLIs ready to use from its integrated terminal.

Per-user isolation
==================

Each ``(build, user)`` pair gets its **own** code-server container
(model ``runbot.build.vscode.session``), not a shared one. The container
mounts the build's sources read-only and the host Postgres socket, but
mounts **only that user's** credentials. Several people can therefore
attach to the same build at once without ever seeing each other's
credentials, and the PR's code does not auto-run next to anyone's
credentials (the side container starts code-server only, never the
build's Odoo run command).

What is shared vs. isolated:

* **Shared, read-only:** ``/data/build`` (the build sources, opened in the
  editor) and the Postgres socket (so the user can query the build's DB).
  Read-only means viewing the code and asking the AI tools about it never
  changes the build and two users never step on each other.
* **Private to each user:** the login folders (``~/.claude``,
  ``~/.codex``, ``~/.gemini``), taken from
  ``<auth_root>/<user_key>/`` on the host, so each user keeps their own
  sign-ins.

``user_key`` is ``<user_id>-<login>`` (e.g. ``7-jjs``): stable across
logins and readable on disk.

How to use
==========

#. Install the module on a runbot.
#. In *Runbot → Configuration → Dockerfiles*, pick the target Dockerfile
   (or a variant), and add a new layer with
   ``layer_type = reference_layer`` pointing at
   ``runbot_attach_vscode.docker_layer_code_server``. Sequence ``200``
   works as a safe default (renders after the standard layers).
#. Rebuild the image and wake a build. *Open VS Code* (in the build's
   action menu or form header) opens a new tab on
   ``/runbot/vscode/<build_id>``, which starts the caller's session
   container, sets a short-lived auth cookie, and bounces to
   ``<scheme>://<dest>-vscode-<user_key>.<host>``.

How it works at run time
========================

Containers start only when needed, one per user: nothing starts when the
build wakes up; a container starts the first time that user clicks *Open
VS Code*.

Clicking the button goes through the controller
``/runbot/vscode/<build_id>`` (the button cannot set the access token by
itself, so it hands off to the controller). The route:

#. Requires a logged-in internal user.
#. Checks the build is running.
#. Calls ``build._ensure_user_vscode_container(user)``: find or create the
   user's ``runbot.build.vscode.session``, pick a free host port, create
   the user's folders, and start the container (same image as the build;
   runs ``code-server`` on ``/data/build``; network on so the AI tools can
   reach their services). If the container is already up, nothing happens.
#. Creates a signed access token — it carries the build id, the user id
   and an expiry, signed with the database secret so it cannot be forged —
   and stores it in the browser. The token is tied to ``<host>`` so the
   browser sends it both to Odoo and to the VS Code address.
#. Sends the browser to the user's VS Code address.

A small addition to ``runbot.nginx_config`` creates one nginx block for
each running session, matching ``<dest>-vscode-<user_key>.<host>`` and
forwarding to that session's port (with the settings code-server needs for
its live connection). Before every request, nginx asks
``/runbot/vscode/auth_check?build=<id>&user=<user_key>``, which checks the
token is valid, not expired, for this build, and owned by that user — so
one user's token cannot open another's container. Without a valid token the
user is sent back to ``/runbot/vscode/<id>`` (which gives a fresh token, or
the login page). code-server itself runs with no password of its own — the
access check lives entirely in nginx. runbot rebuilds its nginx config on
its normal cycle, so new sessions appear automatically.

Lifecycle
=========

* Every editor request marks the session as recently used (at most once a
  minute).
* A scheduled job (every 10 min) stops containers nobody has used for 4
  hours, and removes the sessions it already closed.
* Killing the build stops all of its session containers first. Containers
  start with ``--rm``, so they remove themselves when code-server stops.

The URL helper is a no-op when the build's Dockerfile does not attach
the code-server reference layer (see ``_has_vscode_layer``), so builds
on unrelated Dockerfiles keep working unchanged.

AI CLIs baked into the layer
============================

On top of code-server, the layer installs Node 20 (from NodeSource) and
the following npm-distributed CLIs, available globally in the build
container:

* ``claude`` — `Claude Code <https://docs.claude.com/en/docs/claude-code/overview>`_
  (``@anthropic-ai/claude-code``).
* ``codex`` — `OpenAI Codex CLI <https://github.com/openai/codex>`_
  (``@openai/codex``).
* ``gemini`` — `Google Gemini CLI <https://github.com/google-gemini/gemini-cli>`_
  (``@google/gemini-cli``).
* ``opencode`` — `OpenCode <https://opencode.ai/>`_ (``opencode-ai``).

All four are installed in the same ``RUN`` as code-server to keep the
image layer count low. Image cost: ~1.1 GB of ``/usr/lib/node_modules``
on top of the ~430 MB code-server already adds.

The tools come without any login — each user signs in from the
code-server terminal the first time. Because each user's login folders
are kept on the host, that sign-in is remembered next time and across
rebuilds.

Configuration
=============

System parameters:

``runbot_attach_vscode.url_suffix``
    Suffix between ``build.dest`` and ``<user_key>``. Default: ``vscode``.

``runbot_attach_vscode.scheme``
    URL scheme. Default: ``https``.

``runbot_attach_vscode.session_starting_port``
    Base of the per-session host-port pool (ports increment by 1,
    skipping active sessions). Default: ``20000``.

``runbot_attach_vscode.auth_root``
    Host root for per-user login folders. Default:
    ``~/.adhoc-runbot-auth`` of the runbot user.

The pinned code-server version lives in the layer's ``values`` field
(``CODE_SERVER_VERSION``, default ``4.96.4``). To override per
Dockerfile, set the ``values`` JSON of the consuming
``reference_layer`` — see ``runbot.docker_layer._render_template`` for
the merge order (base + source + caller).

Credits
=======

Authors
~~~~~~~

* ADHOC SA
