# -*- coding: utf-8 -*-
from odoo import fields, models


class HrLeaveType(models.Model):
    _inherit = 'hr.leave.type'

    itv_portal_visible = fields.Boolean(
        "Proposé sur le portail", default=True,
        help="Décochez pour retirer ce type de congé du formulaire de demande du portail employé "
             "(il reste utilisable par les RH dans le back-office).")
