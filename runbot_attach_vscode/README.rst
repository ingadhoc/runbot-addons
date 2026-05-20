=====================
Runbot Attach VS Code
=====================

Bakes `code-server <https://github.com/coder/code-server>`_ (VS Code in
the browser) into runbot Dockerfiles via a reusable
``runbot.docker_layer``. Each ``runbot.build`` exposes an *Open VS Code*
button (internal users only) pointing at the wakeable URL.

How to use
==========

#. Install the module on a runbot.
#. In *Runbot → Configuration → Dockerfiles*, pick the target Dockerfile
   (or a variant), and add a new layer with
   ``layer_type = reference_layer`` pointing at
   ``runbot_attach_vscode.docker_layer_code_server``. Sequence ``200``
   works as a safe default (renders after the standard layers).
#. Rebuild the image and wake a build. The *Open VS Code* button on
   the build form points at ``<scheme>://<dest>-<suffix>.<host>``.

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
