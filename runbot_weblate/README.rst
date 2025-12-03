.. |company| replace:: ADHOC SA

.. |company_logo| image:: https://raw.githubusercontent.com/ingadhoc/maintainer-tools/master/resources/adhoc-logo.png
   :alt: ADHOC SA
   :target: https://www.adhoc.com.ar

.. |icon| image:: https://raw.githubusercontent.com/ingadhoc/maintainer-tools/master/resources/adhoc-icon.png

.. image:: https://img.shields.io/badge/license-AGPL--3-blue.png
   :target: https://www.gnu.org/licenses/agpl
   :alt: License: AGPL-3

==============
Runbot Weblate
==============

Manages GitHub webhooks for Weblate translation integration and provides an API endpoint for external Weblate component creation.

Configuration
=============

System Parameters
-----------------

- `github_transbot_token`: GitHub personal access token with `repo:hooks` permissions
- `runbot_server.token`: Token for API authentication

Weblate Projects
----------------

1. Navigate to **Weblate > Weblate Projects**
2. Create a project with:
   - **Name**: Project identifier
   - **Version**: Odoo version to filter branches
   - **Weblate URL**: Base URL de Weblate (e.g., https://hosted.weblate.org)
3. Assign branches from Runbot (filtered by bundle base and version)
4. Click **Create Webhooks** to configure GitHub webhooks

API Endpoint
============

**GET** `/weblate?token=<token>`

Returns branch data for external scripts:

.. code-block:: json

   {
     "status": "success",
     "data": [
       {"owner": "org", "repo": "repo-name", "branch": "18.0"}
     ]
   }

.. image:: https://odoo-community.org/website/image/ir.attachment/5784_f2813bd/datas
   :alt: Try me on Runbot
   :target: http://runbot.adhoc.com.ar/

Credits
=======

Images
------

* |company| |icon|

Contributors
------------

Maintainer
----------

|company_logo|

This module is maintained by the |company|.

To contribute to this module, please visit https://www.adhoc.com.ar
