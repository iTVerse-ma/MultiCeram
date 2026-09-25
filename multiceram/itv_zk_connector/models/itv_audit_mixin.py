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


class MailThread(models.AbstractModel):
    """Les outils de traçabilité vivent sur la discussion : tout modèle qui en a une en dispose."""
    _inherit = 'mail.thread'

    def _itv_audit(self, summary, details=None):
        """Note interne : ce qui a été fait, le détail élément par élément, puis l'origine.

        `details` accepte une phrase ou une liste de lignes ; les lignes sont présentées en
        liste à puces, comme les notes du journal de synchronisation.
        """
        origin = self._itv_audit_origin()
        # Markup : le corps est du HTML, les valeurs sont échappées une par une.
        body = Markup("<p><b>%s</b></p>") % summary
        if isinstance(details, (list, tuple)):
            lines = [line for line in details if line]
            if lines:
                body += Markup("<ul>%s</ul>") % Markup().join(Markup("<li>%s</li>") % line for line in lines)
        elif details:
            body += Markup("<p>%s</p>") % details
        body += Markup("<p class='text-muted small'>%s</p>") % origin
        for record in self:
            record.message_post(body=body, subtype_xmlid='mail.mt_note')

    @staticmethod
    def _itv_hours(value):
        """Heures en HH:MM, comme partout dans les écrans."""
        value = value or 0.0
        return "%02d:%02d" % (int(value), round((value - int(value)) * 60))

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


class ItvAuditMixin(models.AbstractModel):
    """Ajoute une discussion aux modèles MultiCeram qui n'en ont pas encore."""
    _name = 'itv.audit.mixin'
    _description = "Traçabilité des actions MultiCeram"
    _inherit = ['mail.thread']
