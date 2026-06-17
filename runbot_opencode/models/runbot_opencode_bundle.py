from odoo import fields, models


class RunbotOpencodeBundle(models.Model):
    """A runbot bundle exposed in the OpenCode workspaces.

    Each record is one bundle whose latest finished build is mounted under
    `dir_name` in every user's workspace.
    """

    _name = "runbot.opencode.bundle"
    _description = "Runbot OpenCode mounted bundle"
    _order = "sequence, id"
    _rec_name = "dir_name"

    bundle_id = fields.Many2one(
        "runbot.bundle",
        required=True,
        index=True,
        ondelete="cascade",
    )
    project_id = fields.Many2one(related="bundle_id.project_id")
    trigger_id = fields.Many2one(
        "runbot.trigger",
        required=True,
        domain="[('project_id', '=', project_id)]",
        help="A bundle's build batch has one build per trigger; this picks which "
        "trigger's build is mounted (e.g. the full OBA build vs the modified-modules one).",
    )
    dir_name = fields.Char(
        required=True,
        help="Folder the bundle is mounted under in the workspace (e.g. oba-18). "
        "Must be unique; name it per project when mounting the same version of "
        "several projects (oba-18, odumbo-18).",
    )
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)

    _sql_constraints = [
        ("bundle_uniq", "unique(bundle_id)", "This bundle is already exposed."),
        ("dir_name_uniq", "unique(dir_name)", "The mount folder must be unique."),
    ]

    def _latest_build(self):
        """Latest finished build of this bundle for the chosen trigger, or an
        empty recordset if none. Only builds in 'running' or 'done' count: those
        are up, with their sources checked out on disk."""
        self.ensure_one()
        slots = self.bundle_id.last_done_batch.slot_ids.filtered(lambda s: s.trigger_id == self.trigger_id)
        builds = slots.build_id.filtered(lambda b: b.params_id and b.global_state in ("running", "done"))
        return builds[:1]
