import logging
import os

import requests
from dateutil import parser
from github import Auth, Github, InputGitTreeElement
from markupsafe import Markup
from odoo import api, fields, models
from odoo.exceptions import UserError
from transifex.api import transifex_api

_logger = logging.getLogger(__name__)

# from . import github_login


class RunbotBranch(models.Model):
    _inherit = "runbot.branch"

    transifex_project_id = fields.Many2one("transifex.project")
    last_sync_date = fields.Datetime()
    next_sync_date = fields.Datetime()
    repo_id = fields.Many2one(related="remote_id.repo_id")

    @api.model
    def _cron_sync_translations_to_github(self):
        now = fields.Datetime.now()
        branch = self.search(
            [
                ("transifex_project_id.active", "=", True),
                "|",
                ("next_sync_date", "<", now),
                ("next_sync_date", "=", False),
            ],
            limit=1,
            order="next_sync_date asc",
        )
        if branch:
            try:
                branch.next_sync_date = fields.Datetime.add(now, days=branch.transifex_project_id.periodicity)
                branch.sync_translations_to_github(last_sync_date=branch.last_sync_date)
            except Exception as e:
                _logger.warning("Error al sincronizar transifex a github: %s", e)
                msg = Markup(
                    """
                    <p>Error al sincronizar branch %s, desde transifex project %s a github. Nueva fecha de actualización: %s.</p>
                    <blockquote>%s</blockquote>
                    """
                ) % (branch.display_name, branch.transifex_project_id.slug, branch.next_sync_date, e)
                branch.transifex_project_id.message_post(body=msg)

    def get_push_data(self):
        self.ensure_one()

        gh = Github(auth=Auth.Token(self.transifex_project_id.github_token))
        gh_repo = gh.get_repo("%s/%s" % (self.remote_id.owner, self.remote_id.repo_name))
        gh_content = gh_repo.get_contents("/", ref=self.name)
        modules_names = [x.name for x in gh_content if x.type == "dir"]

        tx_data = [
            (
                self.transifex_project_id.tx_token,
                self.transifex_project_id.organization_slug,
                self.transifex_project_id.slug,
                modules_names,
            )
        ]
        raise UserError(
            "Usar estos datos para probar la exportación:\n"
            '* export tx_data="%s"\n'
            "* crear una base de odoo con esos modulos instalados con: odoo -i %s -d transifex --stop-after-init\n"
            "* si la base es nueva ahora podemos mandar a instalar transifex y el post load va a intentar pushear "
            "traducciones, lo hacemos con: odoo -i transifex_push -d transifex --stop-after-init\n"
            "* si la base ya tiene instalado transifex podemos entrar por shell (odoo-shell -d transifex) y correr:\n"
            "    from odoo.addons.transifex_push import post_init\n"
            "    post_init(env.cr, False)\n"
            "* tener en cuenta que si se quieren exportar idiomas (además de traducción base en inglés) se deben "
            'instalar esos idiomas en la base "transifex"' % (tx_data, ",".join(modules_names))
        )

    def sync_translations_to_github(self, last_sync_date=False):
        """Para hacer commit y push a github usamos ayuda de este isssue
        https://github.com/PyGithub/PyGithub/issues/1628
        Y documentación acá https://pygithub.readthedocs.io/en/latest/github_objects/Repository.html
        y ejemplos acá: https://pygithub.readthedocs.io/en/latest/examples.html
        """
        for rec in self.filtered("transifex_project_id"):
            # We save the date to ensure any new translations made during syncing are captured in the next run.
            start_sync_date = fields.Datetime.now()
            github_token = rec.transifex_project_id.github_token
            if not github_token:
                raise UserError("No hay token de github configurado.")
            gh = Github(auth=Auth.Token(github_token))
            transifex_api.setup(auth=rec.transifex_project_id.tx_token)

            _logger.info(
                "Sync transifex to github for branch %s (tx project %s)",
                rec.display_name,
                rec.transifex_project_id.slug,
            )

            tree_data = []
            gh_repo = gh.get_repo("%s/%s" % (rec.remote_id.owner, rec.remote_id.repo_name))
            gh_content = gh_repo.get_contents("/", ref=rec.name)
            modules_names = [x.name for x in gh_content if x.type == "dir"]

            tx_organization = transifex_api.Organization.get(slug=rec.transifex_project_id.organization_slug)
            tx_project = transifex_api.Project.get(slug=rec.transifex_project_id.slug, organization=tx_organization)
            tx_languages = tx_project.fetch("languages")
            for module_name in modules_names:
                try:
                    # Obtenemos el resource de esta manera ya que filter y get con slug o name no hacen busqueda exacta.
                    # Si coincide en alguna parte, devuelve varios resultados.
                    tx_resource = transifex_api.resources.get("%s:r:%s" % (tx_project.id, module_name))
                except:
                    _logger.warning("Skiping %s as not found on transifex project", module_name)
                    continue
                _logger.info("Sync transifex resource %s", tx_resource.slug)
                for tx_language in tx_languages:
                    if last_sync_date:
                        stats = transifex_api.resource_language_stats.get(
                            project=tx_project, resource=tx_resource, language=tx_language
                        )
                        last_translation_update = stats.last_translation_update and parser.isoparse(
                            stats.last_translation_update
                        ).replace(tzinfo=None)
                        if not last_translation_update or last_translation_update < last_sync_date:
                            _logger.info("Skiping %s as not updated since %s", tx_resource.slug, last_sync_date)
                            continue
                    url = transifex_api.ResourceTranslationsAsyncDownload.download(
                        resource=tx_resource, language=tx_language
                    )
                    translated_content = requests.get(url, timeout=30).content.decode("utf-8")

                    if translated_content:
                        gh_i18n_path = os.path.join("/", tx_resource.slug, "i18n")
                        gh_file_path = os.path.join(gh_i18n_path, tx_language.code + ".po")
                        new_file_blob = gh_repo.create_git_blob(translated_content, "utf-8")
                        tree_data.append(
                            InputGitTreeElement(
                                path=gh_file_path[1:], mode="100644", type="blob", sha=new_file_blob.sha
                            )
                        )
            if tree_data:
                head_sha = gh_repo.get_branch(rec.name).commit.sha
                base_tree = gh_repo.get_git_tree(sha=head_sha)
                tree = gh_repo.create_git_tree(tree_data, base_tree)
                if tree:
                    message = "[I18N] Update translation terms from Transifex %s-%s" % (
                        rec.transifex_project_id.organization_slug,
                        rec.transifex_project_id.slug,
                    )
                    parent = gh_repo.get_git_commit(sha=head_sha)
                    commit = gh_repo.create_git_commit(message, tree, [parent])
                    # TODO alguna forma mejor de hacer esto? la oca comparaba los po con una libreria
                    # (creo que mas complejo)
                    compare = gh_repo.compare(parent.sha, commit.sha)
                    if not compare.files:
                        _logger.info(
                            "No changes on translations on branch %s (tx project %s), avoid pushing to GitHub",
                            rec.display_name,
                            rec.transifex_project_id.slug,
                        )
                    else:
                        _logger.info("Pushing to GitHub")
                        master_refs = gh_repo.get_git_ref("heads/%s" % rec.name)
                        master_refs.edit(sha=commit.sha)
            rec.last_sync_date = start_sync_date
