=====================
Runbot Attach VS Code
=====================

Bakes `code-server <https://github.com/coder/code-server>`_ (VS Code in
the browser) plus a curated set of AI coding CLIs (Claude Code, OpenAI
Codex, Google Gemini, OpenCode) into runbot Dockerfiles via a reusable
``runbot.docker_layer``. Each wakeable ``runbot.build`` whose Dockerfile
attaches that layer exposes an *Open VS Code* button that resolves to a
live code-server session running alongside Odoo inside the build's
container, with the AI CLIs ready to use from its integrated terminal.

How to use
==========

#. Install the module on a runbot.
#. In *Runbot → Configuration → Dockerfiles*, pick the target Dockerfile
   (or a variant), and add a new layer with
   ``layer_type = reference_layer`` pointing at
   ``runbot_attach_vscode.docker_layer_code_server``. Sequence ``200``
   works as a safe default (renders after the standard layers).
#. Rebuild the image and wake a build. The *Open VS Code* entry in the
   build's action menu opens
   ``<scheme>://<dest>-vscode.<host>`` in a new tab, which nginx routes
   to the code-server session listening on container port 8071.

How it works at run time
========================

code-server is started **lazily**: a wakeable build does not start
code-server on every wake-up, only when someone actually clicks the
*Open VS Code* entry. That keeps memory usage off the wake-up budget
(automatic ``run_odoo`` steps inside CI configs would otherwise pay
~150 MB per build for code-server, even when nobody attaches).

On wake-up, the inherited ``_run_run_odoo`` step still reserves the
mapping ``container 8071 → host build.port + 2`` (appended to
``exposed_ports``), because Docker does not let us add port mappings to
a running container later. It does **not** start code-server.

When the user clicks the button, ``action_open_vscode``:

#. Checks that the build container is in the ``RUNNING`` state.
#. Runs ``docker exec`` inside the container (detached) to launch
   ``code-server`` listening on container port 8071. Repeated clicks
   are safe: a second attempt fails with ``EADDRINUSE`` and exits
   without affecting the already-running instance.
#. Briefly polls the host port (up to 5s) so the browser does not race
   against the bind.
#. Returns the ``ir.actions.act_url`` pointing at ``vscode_url``.

A QWeb inherit of ``runbot.nginx_config`` adds a per-build server block
matching ``<dest>-vscode.<host>`` regex that proxies to
``127.0.0.1:<build.port + 2>``, with the WebSocket headers code-server
needs. The standard runbot nginx reload (triggered by ``_run_run_odoo``)
picks the new block up.

Both the run-step extension and the URL helper are no-ops when the
build's Dockerfile does not attach the code-server reference layer
(see ``_has_vscode_layer``), so builds on unrelated Dockerfiles keep
working unchanged.

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

The CLIs ship without credentials — devs authenticate from the
code-server terminal on first use.

Configuration
=============

Two system parameters drive the URL:

``runbot_attach_vscode.url_suffix``
    Suffix appended to ``build.dest``. Default: ``vscode``.

``runbot_attach_vscode.scheme``
    URL scheme. Default: ``https``.

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
