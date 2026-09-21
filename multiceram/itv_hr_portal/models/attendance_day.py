# -*- coding: utf-8 -*-
"""Anomalies envoyées à l'employé : il ne voit que ce que les RH lui adressent.

Parcours : à traiter (interne) → envoyée à l'employé → expliquée → acceptée, renvoyée, ou close.
L'employé n'écrit jamais `anomaly_resolution` : il dépose une explication, les RH tranchent.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

# Les étapes vues par les RH, dans l'ordre : le portail n'est qu'un passage du parcours.
FLOW_STATES = [
    ('open', "À traiter"),
    ('sent', "Envoyée à l'employé"),
    ('submitted', "Expliquée, à décider"),
    ('justified', "Justifiée"),
    ('overtime', "Passée en heures supplémentaires"),
    ('ignored', "Ignorée"),
]
PORTAL_STATES = [
    ('sent', "Envoyée à l'employé"),
    ('submitted', "Expliquée par l'employé"),
    ('accepted', "Acceptée"),
    ('refused', "Refusée"),
]
# États où l'employé peut écrire son explication.
PORTAL_WRITABLE = ('sent',)


class ItvAttendanceDay(models.Model):
    _inherit = 'itv.attendance.day'

    itv_portal_reason = fields.Text("Explication de l'employé", readonly=True, copy=False)
    itv_portal_state = fields.Selection(PORTAL_STATES, string="Justification portail",
                                        readonly=True, copy=False, index=True)
    itv_portal_date = fields.Datetime("Explication envoyée le", readonly=True, copy=False)
    itv_portal_message = fields.Char("Message à l'employé", readonly=True, copy=False,
                                     help="Ce que les RH demandent d'expliquer : visible dans le portail.")
    itv_portal_sent_date = fields.Datetime("Envoyée à l'employé le", readonly=True, copy=False)
    itv_anomaly_overtime = fields.Boolean("Anomalie passée en HS", readonly=True, copy=False,
                                          help="L'anomalie a été requalifiée en heures supplémentaires : "
                                               "la journée suit le circuit de validation N1 / N2.")

    # Statut unique du traitement d'une anomalie : un seul suivi, du signalement à la décision.
    itv_anomaly_flow = fields.Selection(FLOW_STATES, string="Traitement", compute='_compute_itv_anomaly_flow',
                                        store=True, index='btree_not_null')

    @api.depends('anomaly_state', 'itv_portal_state', 'itv_anomaly_overtime')
    def _compute_itv_anomaly_flow(self):
        for day in self:
            if not day.anomaly_state:
                day.itv_anomaly_flow = False
            elif day.itv_anomaly_overtime:
                day.itv_anomaly_flow = 'overtime'
            elif day.anomaly_state == 'justified':
                day.itv_anomaly_flow = 'justified'
            elif day.anomaly_state == 'ignored':
                day.itv_anomaly_flow = 'ignored'
            elif day.itv_portal_state in ('sent', 'submitted'):
                day.itv_anomaly_flow = day.itv_portal_state
            else:
                day.itv_anomaly_flow = 'open'

    # -- Côté RH ----------------------------------------------------------------------------------

    def _itv_portal_send(self, message=False):
        """Rend l'anomalie visible dans le portail de l'employé : lui seul peut l'expliquer ensuite."""
        days = self.filtered(lambda day: day.anomaly_state and day.anomaly_state not in ('justified', 'ignored'))
        if not days:
            raise UserError(_("Aucune journée sélectionnée n'a d'anomalie encore ouverte."))
        result = days.write({
            'itv_portal_state': 'sent',
            'itv_portal_message': message or False,
            'itv_portal_sent_date': fields.Datetime.now(),
        })
        days._itv_audit(_("Anomalie envoyée à l'employé"), message)
        return result

    def action_itv_portal_send(self):
        """Ouvre l'assistant : le responsable écrit ce qu'il attend avant d'envoyer à l'employé."""
        self.check_access('read')
        action = self.env['ir.actions.act_window']._for_xml_id(
            'itv_zk_attendance.itv_attendance_anomaly_wizard_action')
        action['context'] = {
            'active_model': self._name,
            'active_ids': self.ids,
            'default_resolution': 'sent',
        }
        return action

    def action_itv_anomaly_overtime(self):
        """Ouvre l'assistant sur « Passer en heures supplémentaires » pour la journée."""
        self.check_access('read')
        action = self.env['ir.actions.act_window']._for_xml_id(
            'itv_zk_attendance.itv_attendance_anomaly_wizard_action')
        action['context'] = {
            'active_model': self._name,
            'active_ids': self.ids,
            'default_resolution': 'overtime',
        }
        return action

    def action_itv_portal_accept(self):
        """L'explication vaut justification de l'anomalie ; le motif reste celui du responsable."""
        self.check_access('write')
        for day in self.sudo():
            day.write({
                'itv_portal_state': 'accepted',
                'anomaly_resolution': 'justified',
                'anomaly_note': day.anomaly_note or _("Explication de l'employé acceptée"),
            })
            day._itv_audit(_("Explication acceptée"), day.itv_portal_reason)
        return True

    def action_itv_portal_refuse_back(self):
        """Explication refusée : ouvre l'assistant pour écrire ce qu'il manque, puis renvoie à l'employé."""
        self.check_access('write')
        return self.action_itv_portal_send()

    def action_itv_portal_refuse_close(self):
        """Explication refusée et dossier clos : l'anomalie est ignorée, l'employé voit le refus."""
        self.check_access('write')
        for day in self.sudo():
            day.write({
                'itv_portal_state': 'refused',
                'anomaly_resolution': 'ignored',
                'anomaly_note': day.anomaly_note or _("Explication refusée"),
            })
            day._itv_audit(_("Explication refusée, dossier clos"), day.itv_portal_reason)
        return True

    def _itv_refer_overtime(self, hours, rate, note=False):
        """Requalifie l'anomalie en heures supplémentaires et met la journée en circuit N1/N2."""
        if hours <= 0:
            raise UserError(_("Indiquez un nombre d'heures supérieur à zéro."))
        days = self.filtered(lambda day: day.anomaly_state and day.anomaly_state not in ('justified', 'ignored'))
        if not days:
            raise UserError(_("Aucune journée sélectionnée n'a d'anomalie encore ouverte."))
        lines = []
        for day in days:
            attendance = day.attendance_ids[:1]
            lines.append({
                'employee_id': day.employee_id.id,
                'date': day.date,
                'duration': hours,
                'itv_rate': rate,
                'itv_state': 'submitted',       # mise en circuit, comme une proposition classique
                'itv_day_id': day.id,
                'time_start': attendance.check_in or False,
                'time_stop': attendance.check_out or False,
            })
        self.env['hr.attendance.overtime.line'].create(lines)
        days.write({
            'itv_anomaly_overtime': True,
            'anomaly_resolution': 'justified',
            'anomaly_note': note or _("Requalifiée en heures supplémentaires"),
        })
        days._itv_audit(_("Anomalie requalifiée en heures supplémentaires"),
                        _("%(hours)s h au taux %(rate)s %%", hours=("%.2f" % hours).replace('.', ','), rate=rate))
        return True

    # -- Côté portail -----------------------------------------------------------------------------

    def _itv_portal_submit(self, reason):
        """Dépôt depuis le portail : appelé en sudo après contrôle d'appartenance."""
        self._itv_audit(_("Explication déposée par l'employé"), reason)
        return self.write({
            'itv_portal_reason': reason,
            'itv_portal_state': 'submitted',
            'itv_portal_date': fields.Datetime.now(),
        })
