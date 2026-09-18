# -*- coding: utf-8 -*-
from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    itv_biotime_emp_id = fields.Integer("ID employé BioTime", groups='hr.group_hr_user', copy=False, index=True)
    itv_biotime_sync_hash = fields.Char("Empreinte de synchronisation BioTime", groups='hr.group_hr_user', copy=False)
    itv_to_complete = fields.Boolean(
        "Fiche à compléter", groups='hr.group_hr_user', copy=False,
        help="Employé créé par la synchronisation BioTime : poste, contrat et coordonnées restent à renseigner.")
