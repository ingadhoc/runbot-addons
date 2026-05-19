from odoo import models


class BuildConfigStep(models.Model):
    _inherit = "runbot.build.config.step"

    def _run_run_odoo(self, build, force=False):
        """Reserve container port 8071 → host port `build.port + 2` at
        wake-up time when the build's Dockerfile carries the code-server
        reference layer. The port mapping has to be declared at
        `docker run` time (Docker does not let us add port mappings to a
        running container later), but we do not start code-server here —
        it is started lazily by `action_open_vscode` via `docker exec`
        only when the user actually clicks the button.
        """
        run_step_data = super()._run_run_odoo(build, force=force)
        if not run_step_data:
            return run_step_data
        if not build._has_vscode_layer():
            return run_step_data

        run_step_data["exposed_ports"] = list(run_step_data["exposed_ports"]) + [build.port + 2]
        return run_step_data
