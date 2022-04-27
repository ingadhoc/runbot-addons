from odoo import models, fields, api
import github
from transifex.api import transifex_api
from odoo.exceptions import UserError
from dateutil import parser
import os
import requests
import logging

_logger = logging.getLogger(__name__)

# from . import github_login


class RunbotBranch(models.Model):
    _inherit = "runbot.branch"

    transifex_project_id = fields.Many2one('transifex.project')
    next_sync_date = fields.Datetime()
    repo_id = fields.Many2one(related='remote_id.repo_id')

    @api.model
    def _cron_sync_translations_to_github(self):
        now = fields.Datetime.now()
        branch = self.search([('transifex_project_id', '!=', False),'|', ('next_sync_date', '<', now), ('next_sync_date', '=', False)], limit=1)
        if branch:
            try:
                old_next_sync_date = branch.next_sync_date
                # we first change date so that in case we have an error with some branch we continue with next one on
                branch.next_sync_date = fields.Datetime.add(now, days=branch.transifex_project_id.periodicity)
                branch.sync_translations_to_github(next_date=old_next_date)
            except Exception as e:
                _logger.warning('Error al sincronizar transifex a github: %s', e)
                branch.transifex_project_id.message_post(
                    body='Error al sincronizar transifex a github. Esto es lo que obtuvimos: %s' % e)

    def get_push_data(self):
        self.ensure_one()

        gh = github.Github(self.transifex_project_id.github_token)
        gh_repo = gh.get_repo('%s/%s' % (self.remote_id.owner, self.remote_id.repo_name))
        gh_content = gh_repo.get_contents('/', ref=self.name)
        modules_names = [x.name for x in gh_content if x.type == 'dir']

        # no podemos hacer por commit porque para eso hace falta que efectivamente el repo esté descargado
        # eso si, si queremos crear por data un commit podemos usar como ref de get_contents el hash del commit en vez
        # del branch
        # commit = self.env['runbot.commit'].search([('repo_id.remote_ids', '=', self.remote_id.id)], limit=1)
        # if not commit:
        #     raise UserError('No encontramos commit para este branch')
        # modules_names = [x[1] for x in commit._get_available_modules()

        tx_data = [(
            self.transifex_project_id.api_token,
            self.transifex_project_id.organization_slug,
            self.transifex_project_id.slug,
            # como esto lo usamos en bases demo no tenemos commits
            modules_names,
        )]
        raise UserError(
            'Usar estos datos para probar la exportación:\n'
            '* export tx_data="%s"\n'
            '* crear una base de odoo con esos modulos instalados con: odoo -i %s -d transifex --stop-after-init\n'
            '* si la base es nueva ahora podemos mandar a instalar transifex y el post load va a intentar pushear '
            'traducciones, lo hacemos con: odoo -i transifex_push -d transifex --stop-after-init\n'
            '* si la base ya tiene instalado transifex podemos entrar por shell (odoo-shell -d transifex) y correr:\n'
            '    from odoo.addons.transifex_push import post_init\n'
            '    post_init(env.cr, False)\n'
            '* tener en cuenta que si se quieren exportar idiomas (además de traducción base en inglés) se deben '
            'instalar esos idiomas en la base "transifex"' % (tx_data, ','.join(modules_names)))

    def sync_translations_to_github(self, next_date=False):
        """ Para hacer commit y push a github usamos ayuda de este isssue
        https://github.com/PyGithub/PyGithub/issues/1628
        Y documentación acá https://pygithub.readthedocs.io/en/latest/github_objects/Repository.html
        y ejemplos acá: https://pygithub.readthedocs.io/en/latest/examples.html
        """
        for rec in self.filtered('transifex_project_id'):
            gh = github.Github(self.transifex_project_id.github_token)
            transifex_api.setup(auth=rec.transifex_project_id.api_token)

            _logger.info("Sync transifex to github for branch %s (id=%s)", rec.remote_id.name, rec.id)

            tree_data = []
            gh_repo = gh.get_repo('%s/%s' % (rec.remote_id.owner, rec.remote_id.repo_name))
            gh_content = gh_repo.get_contents('/', ref=rec.name)
            modules_names = [x.name for x in gh_content if x.type == 'dir']

            tx_organization = transifex_api.Organization.get(slug=rec.transifex_project_id.organization_slug)
            tx_project = transifex_api.Project.get(
                slug=rec.transifex_project_id.slug, organization=tx_organization)
            tx_resources = tx_project.fetch('resources')
            for tx_resource in tx_resources:
                if tx_resource.slug not in modules_names:
                    _logger.debug('Skiping %s as not found on transifex project', tx_resource.slug)
                    continue
                _logger.info('Sync transifex resource %s', tx_resource.slug)
                for tx_language in tx_project.fetch('languages'):
                    stats = transifex_api.resource_language_stats.get(project=tx_project, resource=tx_resource, language=tx_language)
                    if not stats.last_translation_update:
                        _logger.debug('Skiping %s as not updated since %s', tx_resource.slug, next_date or rec.next_sync_date)
                        continue
                    last_translation_update = parser.isoparse(stats.last_translation_update).replace(tzinfo=None)
                    if not (next_date and last_translation_update > next_date or last_translation_update > rec.next_sync_date):
                        _logger.debug('Skiping %s as not updated since %s', tx_resource.slug, next_date or rec.next_sync_date)
                        continue
                    url = transifex_api.ResourceTranslationsAsyncDownload.download(resource=tx_resource, language=tx_language)
                    # ver contenido
                    translated_content = requests.get(url).text

                    if translated_content:
                        gh_i18n_path = os.path.join('/', tx_resource.slug, "i18n")
                        gh_file_path = os.path.join(gh_i18n_path, tx_language.code + '.po')
                        new_file_blob = gh_repo.create_git_blob(translated_content, 'utf-8')
                        tree_data.append(github.InputGitTreeElement(
                            path=gh_file_path[1:],
                            mode='100644',
                            type='blob',
                            sha=new_file_blob.sha))
            if tree_data:
                head_sha = gh_repo.get_branch(rec.name).commit.sha
                base_tree = gh_repo.get_git_tree(sha=head_sha)
                tree = gh_repo.create_git_tree(tree_data, base_tree)
                if tree:
                    message = '[I18N] Update translation terms from Transifex %s-%s' % (
                        rec.transifex_project_id.organization_slug, rec.transifex_project_id.slug)
                    parent = gh_repo.get_git_commit(sha=head_sha)
                    commit = gh_repo.create_git_commit(
                        message,
                        tree,
                        [parent])
                    # TODO alguna forma mejor de hacer esto? la oca comparaba los po con una libreria
                    # (creo que mas complejo)
                    compare = gh_repo.compare(parent.sha, commit.sha)
                    if not compare.files:
                        _logger.info("No changes on translations, avoid pushing to GitHub")
                    else:
                        _logger.info("Pushing to GitHub")
                        master_refs = gh_repo.get_git_ref('heads/%s' % rec.name)
                        master_refs.edit(sha=commit.sha)
                        
