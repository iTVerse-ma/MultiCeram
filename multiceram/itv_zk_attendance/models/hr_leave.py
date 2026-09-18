# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, models

DAY_FIELDS = {'employee_id', 'holiday_status_id', 'state', 'request_date_from', 'request_date_to', 'date_from', 'date_to'}


class HrLeave(models.Model):
    _inherit = 'hr.leave'

    @api.model_create_multi
    def create(self, vals_list):
        leaves = super().create(vals_list)
        leaves._itv_enqueue_days()
        return leaves

    def write(self, vals):
        if not DAY_FIELDS & set(vals):
            return super().write(vals)
        before = self._itv_day_pairs()
        result = super().write(vals)
        self._itv_enqueue_days(before)
        return result

    def unlink(self):
        pairs = self._itv_day_pairs()
        result = super().unlink()
        self.env['itv.attendance.dirty']._enqueue(pairs)
        return result

    def _itv_day_pairs(self):
        """Congés et jours de repos s'affichent sur les journées : chaque jour couvert est à recalculer."""
        pairs = []
        for leave in self:
            if not (leave.employee_id and leave.request_date_from):
                continue
            day = leave.request_date_from
            last = leave.request_date_to or leave.request_date_from
            while day <= last:
                pairs.append((leave.employee_id.id, day))
                day += timedelta(days=1)
        return pairs

    def _itv_enqueue_days(self, extra=()):
        self.env['itv.attendance.dirty']._enqueue(self._itv_day_pairs() + list(extra))
