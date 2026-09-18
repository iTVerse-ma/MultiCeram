# -*- coding: utf-8 -*-
from odoo import fields, models


class HrDepartment(models.Model):
    _inherit = 'hr.department'

    itv_biotime_dept_id = fields.Integer("ID département BioTime", copy=False, index=True)
    itv_biotime_dept_code = fields.Char("Code département BioTime", copy=False)
