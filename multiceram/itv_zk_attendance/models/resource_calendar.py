# -*- coding: utf-8 -*-
"""Horaires de travail natifs, complétés de ce que le 3×8 exige.

Odoo décrit déjà un horaire par jour de la semaine : début, fin, pause. Il lui manque deux
choses pour un poste de nuit : dire qu'il traverse minuit, et tolérer un léger retard. Le reste
(heures attendues, bornes de la journée) se lit dans les lignes de l'horaire.
"""
from datetime import datetime, timedelta

from odoo import _, api, fields, models

# Les lignes de pause ne comptent pas dans les heures dues.
WORK_PERIODS = ('morning', 'afternoon')
# Sépare le soir du petit matin dans un poste de nuit.
MIDDAY = 12.0


class ResourceCalendar(models.Model):
    _inherit = 'resource.calendar'

    itv_is_shift = fields.Boolean(
        "Poste de travail", help="Horaire utilisé comme poste dans le calcul des présences : "
                                 "ses bornes servent au retard et au départ anticipé.")
    itv_code = fields.Char("Code", help="Repère court du poste (P1, P2, P3…), utilisé dans les plannings.")
    itv_overnight = fields.Boolean(
        "Passe minuit",
        help="Poste de nuit : les pointages d'après minuit sont rattachés à la journée où le poste commence. "
             "Odoo ne sait pas écrire une ligne qui traverse minuit : posez le soir (ex. 22h–24h) et le "
             "lendemain matin (ex. 0h–6h).")
    itv_late_tolerance = fields.Integer(
        "Tolérance de retard (min)", help="En deçà, l'arrivée n'est pas comptée en retard.")

    def _itv_lines_for(self, weekday, part=None):
        """Lignes de travail d'un jour de la semaine ; `part` sépare la soirée du petit matin.

        Un poste de nuit s'écrit en deux morceaux sur deux jours : le soir (22h–24h) appartient
        à la journée qui commence, le matin (0h–6h) à celle de la veille.
        """
        lines = self.attendance_ids.filtered(
            lambda line: int(line.dayofweek) == weekday and (line.day_period or 'morning') in WORK_PERIODS)
        if part == 'evening':
            return lines.filtered(lambda line: line.hour_from >= MIDDAY)
        if part == 'morning':
            return lines.filtered(lambda line: line.hour_to <= MIDDAY)
        return lines

    def _itv_expected_hours(self, day):
        """Heures dues pour cette journée, d'après les lignes de l'horaire.

        Un horaire flexible n'a pas de lignes : c'est alors la moyenne journalière qui fait foi.
        """
        self.ensure_one()
        if not self.attendance_ids:
            return self.hours_per_day or 0.0
        if self.itv_overnight:
            evening = self._itv_lines_for(day.weekday(), 'evening')
            morning = self._itv_lines_for((day.weekday() + 1) % 7, 'morning')
            return sum(line.hour_to - line.hour_from for line in evening + morning)
        return sum(line.hour_to - line.hour_from for line in self._itv_lines_for(day.weekday()))

    def _itv_day_bounds(self, day):
        """Début et fin du poste pour une journée, en heure locale ; None si l'horaire est flexible."""
        self.ensure_one()
        midnight = datetime.combine(day, datetime.min.time())
        if self.itv_overnight:
            evening = self._itv_lines_for(day.weekday(), 'evening')
            morning = self._itv_lines_for((day.weekday() + 1) % 7, 'morning')
            if not evening:
                return None, None
            end = midnight + timedelta(days=1, hours=max(morning.mapped('hour_to'))) if morning else None
            return midnight + timedelta(hours=min(evening.mapped('hour_from'))), end
        lines = self._itv_lines_for(day.weekday())
        if not lines:
            return None, None
        return (midnight + timedelta(hours=min(lines.mapped('hour_from'))),
                midnight + timedelta(hours=max(lines.mapped('hour_to'))))

    @api.depends('itv_code', 'name')
    def _compute_display_name(self):
        super()._compute_display_name()
        for calendar in self.filtered('itv_code'):
            calendar.display_name = "%s — %s" % (calendar.itv_code, calendar.name)
