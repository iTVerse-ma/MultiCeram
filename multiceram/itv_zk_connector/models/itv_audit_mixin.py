# -*- coding: utf-8 -*-
"""Journal des actions : qui a fait quoi, quand, et depuis où.

Les écrans MultiCeram touchent à la paie : chaque décision (validation, refus, justification,
envoi à l'employé, écriture vers la pointeuse) laisse une trace dans la discussion de la fiche,
avec l'origine de la demande. Les traces sont des notes internes : l'employé ne les reçoit pas.
"""
from markupsafe import Markup

from odoo import api, models
from odoo.http import request

# En-têtes posés par le proxy : la vraie adresse du client s'y trouve.
FORWARDED_HEADERS = ('X-Forwarded-For', 'X-Real-IP')


class ItvAuditMixin(models.AbstractModel):
    _name = 'itv.audit.mixin'
    _description = "Traçabilité des actions MultiCeram"
    _inherit = ['mail.thread']

    def _itv_audit(self, summary, details=None):
        """Note interne : l'action, son auteur et son origine."""
        origin = self._itv_audit_origin()
        # Markup : le corps est du HTML, les valeurs sont échappées une par une.
        body = Markup("<p><b>%s</b></p>") % summary
        if details:
            body += Markup("<p>%s</p>") % details
        body += Markup("<p class='text-muted small'>%s</p>") % origin
        for record in self:
            record.message_post(body=body, subtype_xmlid='mail.mt_note')

    @api.model
    def _itv_audit_origin(self):
        """D'où vient la demande : portail, écran interne, ou traitement automatique."""
        user = self.env.user.display_name
        if not request:
            # Cron, script ou import : pas de navigateur derrière.
            return "%s — traitement automatique" % user
        path = request.httprequest.path or ''
        if path.startswith('/my') or path.startswith('/portal'):
            where = "portail employé"
        elif path.startswith('/iclock') or path.startswith('/itv/kiosk'):
            where = "pointeuse"
        else:
            where = "interface interne"
        address = self._itv_audit_address()
        return "%s — %s%s" % (user, where, (", adresse %s" % address) if address else "")

    @api.model
    def _itv_audit_address(self):
        if not request:
            return False
        for header in FORWARDED_HEADERS:
            value = request.httprequest.headers.get(header)
            if value:
                # X-Forwarded-For liste les relais : le client est en tête.
                return value.split(',')[0].strip()
        return request.httprequest.remote_addr
