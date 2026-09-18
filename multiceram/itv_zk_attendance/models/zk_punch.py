# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import models

LEGACY_PUNCH_FIELDS = {'duplicate', 'to_delete', 'date_override', 'employee_id'}


class ItvZkPunch(models.Model):
    _inherit = 'itv.zk.punch'

    def _on_punches_imported(self):
        super()._on_punches_imported()
        self._itv_enqueue_legacy()

    def write(self, vals):
        previous = [(punch.employee_id.id, punch.date_override) for punch in self] if 'date_override' in vals else []
        result = super().write(vals)
        if LEGACY_PUNCH_FIELDS & set(vals):
            self._itv_enqueue_legacy()
            self.env['itv.attendance.dirty']._enqueue(previous)
        return result

    def _itv_enqueue_legacy(self):
        # La veille et le lendemain aussi : un poste de nuit prend les sorties du jour suivant.
        pairs = []
        for punch in self.filtered('employee_id'):
            for day in (punch.punch_date, punch.date_override):
                if day:
                    pairs += [(punch.employee_id.id, day + timedelta(days=offset)) for offset in (-1, 0, 1)]
        self.env['itv.attendance.dirty']._enqueue(pairs)
