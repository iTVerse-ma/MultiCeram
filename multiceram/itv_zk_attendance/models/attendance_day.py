# -*- coding: utf-8 -*-
import logging
from datetime import datetime, time, timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, format_date
from odoo.addons.itv_zk_connector.services.timeutils import local_to_utc, parse_local, utc_to_local

from ..services.legacy_engine import (
    LegacyEmployeeSettings,
    LegacyHoliday,
    LegacyLeave,
    LegacyOvertimeRow,
    LegacyPageError,
    LegacyPunch,
    compute_legacy_page,
)
from .hr_attendance_overtime_line import DECLARED_STATES, ITV_STATES

_logger = logging.getLogger(__name__)

LEGACY_ENGINE_VERSION = 'nabi_hr-2025.1'
LEGACY_DURATIONS = ('pause', 'heures', 'heures25', 'hs', 'hs25_raw', 'hs25', 'hs50', 'abs25')
WEEKDAYS = [('0', "Lundi"), ('1', "Mardi"), ('2', "Mercredi"), ('3', "Jeudi"), ('4', "Vendredi"), ('5', "Samedi"), ('6', "Dimanche")]
LEGACY_ERRORS = [
    (LegacyPageError.ROUND_OVERFLOW, "Arrivée après 23:44"),
    (LegacyPageError.CARRY_LAST_DAY, "Report de nuit le dernier jour du mois"),
    (LegacyPageError.MULTIPLE_RESTAURANT, "Plusieurs passages restaurant"),
    (LegacyPageError.MULTIPLE_OVERTIME_ROWS, "Plusieurs lignes d'heures supplémentaires"),
]
ANOMALY_STATES = [('open', "À traiter"), ('justified', "Justifiée"), ('ignored', "Ignorée")]
ANOMALY_LABELS = (
    ('lg_presence_anomaly', "Présence impaire"),
    ('lg_door_anomaly', "Porte impaire"),
    ('lg_detected_present', "Détecté présent"),
    ('attendance_conflict', "Présence non reportée"),
)
REPORT_TOTALS = (
    'lg_worked_day', 'lg_absent_day', 'lg_heures', 'lg_heures25', 'lg_pause', 'lg_abs25', 'lg_hs', 'lg_hs25',
    'lg_total_hs_declare', 'lg_total_hs25', 'lg_total_hs50', 'lg_total_hs100', 'overtime_hours',
)
ACTIVE_LEAVE_STATES = ('confirm', 'validate1', 'validate')
DEFAULT_TZ = 'Africa/Casablanca'


def _hours(value):
    return round(value.total_seconds() / 3600.0, 6)


class ItvAttendanceDay(models.Model):
    _name = 'itv.attendance.day'
    _inherit = ['itv.audit.mixin']
    _description = "Journée de pointage"
    _order = 'date desc, employee_id'
    _rec_name = 'date'

    employee_id = fields.Many2one('hr.employee', string="Employé", required=True, ondelete='cascade')
    date = fields.Date("Date", required=True, index=True)
    company_id = fields.Many2one(related='employee_id.company_id', store=True, index=True)
    department_id = fields.Many2one('hr.department', string="Département", help="Département de l'employé au moment du calcul.")
    weekday = fields.Selection(WEEKDAYS, string="Jour", compute='_compute_weekday', store=True)
    is_holiday = fields.Boolean("Jour férié")
    has_leave = fields.Boolean("Congé")
    is_rest_day = fields.Boolean("Jour de repos", help="Congé « Jour de repos » posé sur cette date (colonne JR de la page d'origine).")
    has_manual_overtime = fields.Boolean("Saisie HS")

    # -- Calcul historique (nabi_hr) --------------------------------------------------------
    lg_period = fields.Date("Mois de calcul", help="Le calcul historique se fait par mois, comme la page d'origine.")
    lg_engine_version = fields.Char("Version du calcul historique")
    lg_error = fields.Selection(LEGACY_ERRORS, string="Calcul impossible",
                                help="La page d'origine plantait sur ce mois : aucun chiffre n'est produit.")
    lg_punch_count = fields.Integer("Nombre de pointages")
    lg_clean_count = fields.Integer("Pointages retenus")
    lg_carried_count = fields.Integer("Reportés de J+1")
    lg_first_punch = fields.Char("Premier pointage")
    lg_last_punch = fields.Char("Dernier pointage")
    lg_first_punch_id = fields.Many2one('itv.zk.punch', string="Premier pointage retenu", ondelete='set null')
    lg_last_punch_id = fields.Many2one('itv.zk.punch', string="Dernier pointage retenu", ondelete='set null')
    lg_pause = fields.Float("Pause (h)")
    lg_heures = fields.Float("H. présence (h)")
    lg_heures25 = fields.Float("H. normales (h)")
    lg_hs = fields.Float("HS (h)")
    lg_hs25_raw = fields.Float("HS 25 % brutes (h)")
    lg_hs25 = fields.Float("HS corrigées (h)")
    lg_hs50 = fields.Float("HS dimanche (h)")
    lg_abs25 = fields.Float("Absence (h)")
    lg_anomalies = fields.Char("Codes d'anomalie")
    lg_presence_anomaly = fields.Boolean("Pointage de présence impair")
    lg_door_anomaly = fields.Boolean("Pointage de porte impair")
    lg_detected_present = fields.Boolean("Détecté présent")
    # Contributions aux totaux du pied de la page d'origine : la somme native donne le même total.
    lg_total_hs25 = fields.Float("Total 25 % (h)", help="HS 25 % brutes, négatives comprises, plus la saisie manuelle.")
    lg_total_hs_declare = fields.Float("HS déclarées (h)")
    lg_total_hs50 = fields.Float("Total 50 % (h)", help="Saisie manuelle seulement, comme le pied de page d'origine.")
    lg_total_hs100 = fields.Float("Total 100 % (h)")
    lg_hs50_column = fields.Float("Colonne 50 % (h)", help="Saisie manuelle, sinon HS du dimanche : colonne jour de la page d'origine.")
    lg_worked_day = fields.Integer("Jour travaillé")
    lg_absent_day = fields.Integer("Jour sans pointage")

    # -- Anomalies ----------------------------------------------------------------------------------
    anomaly_resolution = fields.Selection([('justified', "Justifiée"), ('ignored', "Ignorée")],
                                          string="Traitement de l'anomalie", copy=False, tracking=True)
    anomaly_note = fields.Char("Motif de l'anomalie", tracking=True)
    itv_calendar_id = fields.Many2one(
        'resource.calendar', string="Horaire", readonly=True, ondelete='set null', index='btree_not_null',
        help="Horaire appliqué à cette journée, d'après le planning du responsable ou la fiche de l'employé.")
    itv_late_minutes = fields.Integer("Retard (min)", readonly=True,
                                      help="Minutes entre le début du poste et le premier pointage, tolérance déduite.")
    itv_early_minutes = fields.Integer("Départ anticipé (min)", readonly=True,
                                       help="Minutes entre le dernier pointage et la fin du poste.")
    anomaly_custom_type_ids = fields.Many2many(
        'itv.attendance.anomaly.type', 'itv_day_anomaly_type_rel', 'day_id', 'type_id',
        string="Règles déclenchées", readonly=True,
        help="Types d'anomalie créés par les RH dont la condition est remplie par cette journée.")
    anomaly_state = fields.Selection(ANOMALY_STATES, string="Anomalie", compute='_compute_anomaly_state', store=True,
                                     help="Pointage de présence ou de porte impair, détecté présent, ou présence non reportée.")

    # -- Présences (hr.attendance) ----------------------------------------------------------------
    attendance_ids = fields.One2many('hr.attendance', 'itv_day_id', string="Présence")
    attendance_conflict = fields.Boolean(
        "Présence non reportée",
        help="La journée chevauche une autre présence de l'employé dans Présences : aucune présence n'a été créée.")

    # -- Heures supplémentaires (circuit de validation) -------------------------------------------
    overtime_line_ids = fields.One2many('hr.attendance.overtime.line', 'itv_day_id', string="Heures supplémentaires")
    overtime_hours = fields.Float("HS en circuit (h)", compute='_compute_overtime', store=True,
                                  help="Heures supplémentaires proposées ou déclarées pour la journée, hors refus.")
    overtime_state = fields.Selection(ITV_STATES, string="Validation HS", compute='_compute_overtime', store=True)

    # -- Affichage ---------------------------------------------------------------------------------
    punch_summary = fields.Char("Pointages", compute='_compute_punch_summary',
                                help="Premier et dernier pointage retenus, (J+1) si la sortie est le lendemain, et nombre de pointages.")
    first_punch_label = fields.Char("Premier pointage", compute='_compute_punch_labels')
    last_punch_label = fields.Char("Dernier pointage", compute='_compute_punch_labels',
                                   help="J+1 quand la sortie est le lendemain (poste de nuit).")
    anomaly_label = fields.Char("Type d'anomalie", compute='_compute_anomaly_label')

    _employee_date_uniq = models.UniqueIndex('(employee_id, date)', "Une seule journée par employé et par date.")

    @api.depends('lg_first_punch', 'lg_last_punch', 'lg_punch_count', 'date')
    def _compute_punch_summary(self):
        for day in self:
            count = "(%s)" % day.lg_punch_count if day.lg_punch_count else ""
            first, last = day.lg_first_punch, day.lg_last_punch
            if first and last and first != last:
                next_day = " J+1" if day.date and last[:10] > fields.Date.to_string(day.date) else ""
                day.punch_summary = "%s → %s%s %s" % (first[11:16], last[11:16], next_day, count)
            elif first:
                day.punch_summary = "%s %s" % (first[11:16], count)
            else:
                day.punch_summary = "— %s" % count if count else False

    @api.depends('lg_first_punch', 'lg_last_punch', 'date')
    def _compute_punch_labels(self):
        for day in self:
            first, last = day.lg_first_punch, day.lg_last_punch
            day.first_punch_label = first[11:16] if first else False
            next_day = " J+1" if last and day.date and last[:10] > fields.Date.to_string(day.date) else ""
            day.last_punch_label = "%s%s" % (last[11:16], next_day) if last else False

    @api.depends(*[name for name, _label in ANOMALY_LABELS])
    @api.depends('lg_presence_anomaly', 'lg_door_anomaly', 'lg_detected_present', 'attendance_conflict',
                 'anomaly_custom_type_ids')
    def _compute_anomaly_label(self):
        labels = self.env['itv.attendance.anomaly.type']._labels_by_field()
        for day in self:
            found = [label for name, label in labels.items() if day[name]]
            found += day.anomaly_custom_type_ids.mapped('name')
            day.anomaly_label = ", ".join(found) or False

    def _itv_apply_shift(self):
        """Horaire appliqué à la journée ; retard et départ anticipé mesurés sur ses bornes."""
        Plan = self.env['itv.employee.shift']
        for day in self:
            calendar = Plan._calendar_for(day.employee_id, day.date)
            vals = {'itv_calendar_id': calendar.id or False, 'itv_late_minutes': 0, 'itv_early_minutes': 0}
            first = parse_local(day.lg_first_punch) if day.lg_first_punch else None
            last = parse_local(day.lg_last_punch) if day.lg_last_punch else None
            worked_day = first and not day.has_leave and not day.is_holiday and not day.is_rest_day
            if calendar and worked_day:
                start, end = calendar._itv_day_bounds(day.date)
                if start:
                    late = (first - start).total_seconds() / 60.0
                    vals['itv_late_minutes'] = max(int(round(late)) - (calendar.itv_late_tolerance or 0), 0)
                if end and last:
                    vals['itv_early_minutes'] = max(int(round((end - last).total_seconds() / 60.0)), 0)
            day._write_changed(vals)

    @api.model
    def _apply_custom_anomaly_types(self, days=None, types=None):
        """Applique les conditions des types créés par les RH aux journées indiquées.

        Sans journées, la condition est rejouée sur tout l'historique : c'est le bouton
        « Appliquer maintenant » de la fiche du type.
        """
        AnomalyType = self.env['itv.attendance.anomaly.type'].sudo()
        types = types if types is not None else AnomalyType._custom_types()
        types = types.filtered(lambda record: not record.is_builtin)
        if not types:
            return
        Day = self.sudo()
        for anomaly_type in types:
            scope = [('id', 'in', days.ids)] if days is not None else []
            matched = Day.search(anomaly_type._condition_domain() + scope) if anomaly_type.active else Day.browse()
            current = Day.search([('anomaly_custom_type_ids', 'in', anomaly_type.id)] + scope)
            (matched - current).write({'anomaly_custom_type_ids': [(4, anomaly_type.id)]})
            (current - matched).write({'anomaly_custom_type_ids': [(3, anomaly_type.id)]})

    def _report_pages(self):
        """PDF mensuel : une page par employé et par mois, journées dans l'ordre, totaux du pied de page d'origine."""
        pages = []
        for (employee, month), days in self.grouped(lambda day: (day.employee_id, day.date.replace(day=1))).items():
            days = days.sorted('date')
            totals = {name: sum(days.mapped(name)) for name in REPORT_TOTALS}
            totals.update(
                days=len(days),
                leaves=len(days.filtered('has_leave')),
                holidays=len(days.filtered('is_holiday')),
                rest_days=len(days.filtered('is_rest_day')),
            )
            pages.append({
                'employee': employee.sudo(),
                'month': format_date(self.env, month, date_format='MMMM y').capitalize(),
                'days': days,
                'totals': totals,
            })
        return sorted(pages, key=lambda page: (page['employee'].name or '', page['days'][:1].date))

    @api.depends('date')
    def _compute_weekday(self):
        for day in self:
            day.weekday = str(day.date.weekday()) if day.date else False

    @api.depends('employee_id', 'date')
    def _compute_display_name(self):
        for day in self:
            day.display_name = "%s — %s" % (day.employee_id.name or '', format_date(self.env, day.date)) if day.date else ''

    @api.depends('lg_presence_anomaly', 'lg_door_anomaly', 'lg_detected_present', 'attendance_conflict',
                 'anomaly_resolution', 'anomaly_custom_type_ids')
    def _compute_anomaly_state(self):
        # Seuls les types d'anomalie actifs (Configuration) signalent une journée.
        names = self.env['itv.attendance.anomaly.type']._active_fields()
        for day in self:
            has_anomaly = any(day[name] for name in names) or bool(day.anomaly_custom_type_ids)
            day.anomaly_state = (day.anomaly_resolution or 'open') if has_anomaly else False

    @api.depends('overtime_line_ids.duration', 'overtime_line_ids.itv_state')
    def _compute_overtime(self):
        for day in self:
            lines = day.overtime_line_ids
            day.overtime_hours = sum(lines.filtered(lambda line: line.itv_state != 'refused').mapped('duration'))
            day.overtime_state = lines[:1].itv_state

    # -- Recalcul -------------------------------------------------------------------------------

    @api.model
    def _recompute_days(self, employee, dates, full_month_threshold=None):
        """Recalcule les journées demandées, mois par mois.

        Une journée se calcule avec le lendemain (report de nuit). Le mois entier n'est repris que
        lorsqu'il le faut : mois jamais calculé, mois où la page d'origine plantait, pointages
        déplacés à la main, ou trop de journées touchées d'un coup.
        """
        employee = employee.sudo()
        months = {}
        for date in dates:
            months.setdefault(date.replace(day=1), set()).add(date)
        for month, month_dates in months.items():
            if self._period_closed(employee, month, len(month_dates)):
                continue
            end = month + relativedelta(months=1, days=-1)
            existing = self.search([('employee_id', '=', employee.id), ('date', '>=', month), ('date', '<=', end)])
            whole_month = (
                not existing
                or existing.filtered('lg_error')
                or (full_month_threshold and len(month_dates) > full_month_threshold)
                or self._has_moved_punches(employee, month, end)
            )
            if whole_month:
                # Demande explicite : la journée est créée même sans le moindre pointage,
                # sinon une absence complète ne laisserait aucune ligne à l'écran.
                self._recompute_legacy_month(employee, month, force=True)
                continue
            for date in sorted(month_dates):
                self._recompute_legacy_day(employee, date)

    @api.model
    def _recompute_legacy_day(self, employee, date):
        """Recalcule une seule journée ; le mois entier seulement si la fenêtre ne suffit pas."""
        if date > fields.Date.context_today(self):
            return
        vals = self._legacy_day_vals_for(employee, date)
        if vals is None:
            return self._recompute_legacy_month(employee, date.replace(day=1))
        day = self.search([('employee_id', '=', employee.id), ('date', '=', date)], limit=1)
        if day:
            day._write_changed(vals)
        else:
            self.create(dict(vals, employee_id=employee.id, date=date))
        days = self.search([('employee_id', '=', employee.id), ('date', '=', date)])
        days._itv_apply_shift()
        self._apply_custom_anomaly_types(days=days)
        self._sync_attendances(employee, date, date)

    @api.model
    def _legacy_day_vals_for(self, employee, date):
        """Chiffres d'une journée, calculés sur la plus petite fenêtre qui donne le résultat du mois.

        Rend None quand la fenêtre ne peut pas reproduire le mois : au mois entier de le faire.
        """
        if date > fields.Date.context_today(self):
            return None
        month = date.replace(day=1)
        start = self._legacy_window_start(employee, date, month)
        if start is None:
            return None
        # Le lendemain pour le report de nuit, sans sortir du mois : le dernier jour du mois plantait
        # dans la page d'origine s'il reportait, et seul le calcul du mois reproduit ce plantage.
        end = min(date + timedelta(days=1), month + relativedelta(months=1, days=-1))
        try:
            page = compute_legacy_page(
                start, end, self._legacy_punches(employee, start, end),
                self._legacy_settings(employee, start, end),
                holidays=self._legacy_holidays(employee),
                leaves=self._legacy_leaves(employee),
                overtime_rows=self._legacy_overtime_rows(employee, start, end),
                rest_days=self._rest_days(employee, start, end),
            )
        except LegacyPageError:
            return None
        vals = self._legacy_day_vals(page.days[(date - start).days])
        vals.update(lg_period=month, lg_engine_version=LEGACY_ENGINE_VERSION, department_id=employee.department_id.id,
                    is_rest_day=bool(self._rest_days(employee, date, date)))
        return vals

    @api.model
    def _legacy_window_start(self, employee, date, month, max_back=7):
        """Jour d'où partir pour retrouver les chiffres du mois.

        Une journée de nuit prend les sorties du lendemain : une journée qui ne commence pas par une
        sortie n'a donc rien pu laisser à la veille, la fenêtre peut commencer là.
        """
        start = date
        while start > month and not self._legacy_starts_clean(employee, start):
            if (date - start).days >= max_back:
                return None
            start -= timedelta(days=1)
        return start

    @api.model
    def _legacy_starts_clean(self, employee, date):
        settings = self._legacy_settings(employee, date, date)
        punches = [punch for punch in self._legacy_punches(employee, date, date)
                   if not punch.duplicate and not punch.to_delete and not (settings.ignore_uhf and punch.uhf_bridge)]
        punches.sort(key=lambda punch: (punch.local_time, punch.id))
        # Les deux premiers : un doublon « 5 min » écarté à l'affichage peut cacher une sortie.
        return all(punch.direction != 'out' for punch in punches[:2])

    @api.model
    def _recompute_legacy_month(self, employee, month, force=False):
        employee = employee.sudo()
        start = month.replace(day=1)
        end = start + relativedelta(months=1, days=-1)
        if self._period_closed(employee, start):
            return
        existing = {day.date: day for day in self.search([('employee_id', '=', employee.id), ('date', '>=', start), ('date', '<=', end)])}
        punches = self._legacy_punches(employee, start, end)
        if not punches and not existing and not force:
            # Mois sans pointage et sans demande explicite : rien à écrire.
            return
        try:
            page = compute_legacy_page(
                start, end, punches,
                self._legacy_settings(employee, start, end),
                holidays=self._legacy_holidays(employee),
                leaves=self._legacy_leaves(employee),
                overtime_rows=self._legacy_overtime_rows(employee, start, end),
                rest_days=self._rest_days(employee, start, end),
            )
            rows = {day.day: self._legacy_day_vals(day) for day in page.days}
        except LegacyPageError as exc:
            # La page d'origine plantait sur ce mois : aucun chiffre, la cause est gardée sur chaque jour.
            rows = {start + timedelta(days=offset): dict(self._legacy_empty_vals(), lg_error=exc.kind)
                    for offset in range((end - start).days + 1)}
        common = {'lg_period': start, 'lg_engine_version': LEGACY_ENGINE_VERSION, 'department_id': employee.department_id.id}
        rest_days = self._rest_days(employee, start, end)
        today = fields.Date.context_today(self)
        to_create = []
        for day, vals in rows.items():
            if day > today:
                # Journée pas encore arrivée : elle sera écrite le jour même, pas en avance.
                continue
            vals.update(common, is_rest_day=day in rest_days)
            if day in existing:
                existing[day]._write_changed(vals)
            else:
                to_create.append(dict(vals, employee_id=employee.id, date=day))
        if to_create:
            self.create(to_create)
        days = self.search([('employee_id', '=', employee.id), ('date', '>=', start), ('date', '<=', end)])
        days._itv_apply_shift()
        self._apply_custom_anomaly_types(days=days)
        self._sync_attendances(employee, start, end)

    def _write_changed(self, vals):
        """N'écrit que ce qui change vraiment : une journée identique ne touche plus ni la base ni Présences."""
        self.ensure_one()
        changed = {}
        for name, value in vals.items():
            current = self[name]
            if isinstance(current, models.Model):
                current = current.id or False
            if isinstance(current, float) or isinstance(value, float):
                if float_compare(current or 0.0, value or 0.0, precision_digits=6):
                    changed[name] = value
            elif current != (value or False):
                changed[name] = value
        if changed:
            self.write(changed)
        return bool(changed)

    @api.model
    def _period_closed(self, employee, month, changes=1):
        """Période clôturée : les chiffres payés ne bougent plus, les modifications tardives sont comptées."""
        period = self.env['itv.attendance.period'].sudo().search(
            [('company_id', '=', employee.company_id.id), ('month', '=', month), ('state', '=', 'closed')], limit=1)
        if not period:
            return False
        period.skipped_count += changes
        return True

    @api.model
    def _has_moved_punches(self, employee, start, end):
        """Un pointage rattaché à la main à une autre date : seul le mois entier le replace au bon jour."""
        return bool(self.env['itv.zk.punch'].sudo().search_count([
            ('employee_id', '=', employee.id), ('punch_date', '>=', start), ('punch_date', '<=', end),
            ('date_override', '!=', False),
        ], limit=1))

    @api.model
    def _legacy_punches(self, employee, start, end):
        # Un poste de nuit finit le lendemain : on va chercher les pointages du jour suivant.
        calendars = self.env['itv.employee.shift']._calendars_for_range(employee, start, end + timedelta(days=1))
        overnight = any(calendar.itv_overnight for calendar in calendars.values())
        punches = self.env['itv.zk.punch'].sudo().search([
            ('employee_id', '=', employee.id), ('punch_date', '>=', start),
            ('punch_date', '<=', end + timedelta(days=1) if overnight else end),
        ])
        rows = []
        for punch in punches:
            local = parse_local(punch.punch_local)
            rows.append(LegacyPunch(
                id=punch.id,
                local_time=local,
                usage=None if punch.terminal_id.itv_legacy_presence else (punch.usage or None),
                direction=punch.direction if punch.direction in ('in', 'out') else None,
                duplicate=punch.duplicate,
                to_delete=punch.to_delete,
                # La correction manuelle prime sur le rattachement automatique du poste.
                date_override=punch.date_override or self._itv_shift_day(calendars, local, end),
                uhf_bridge=punch.terminal_id.is_uhf_bridge,
            ))
        return rows

    @api.model
    def _itv_shift_day(self, calendars, local, end):
        """Journée à laquelle rattacher un pointage d'après-minuit d'un poste de nuit."""
        previous = local.date() - timedelta(days=1)
        calendar = calendars.get(previous)
        if not calendar or not calendar.itv_overnight:
            return None
        _start, finish = calendar._itv_day_bounds(previous)
        # Le poste de la veille court jusqu'à sa fin : tout ce qui précède lui revient.
        if finish and local < finish + timedelta(hours=2):
            return previous if previous <= end else None
        return None

    @api.model
    def _legacy_settings(self, employee, start=None, end=None):
        # Les postes peuvent changer d'un jour à l'autre : la norme suit le poste du jour.
        by_date = ()
        if start and end:
            calendars = self.env['itv.employee.shift']._calendars_for_range(employee, start, end)
            by_date = tuple((day, calendar._itv_expected_hours(day)) for day, calendar in calendars.items()
                            if calendar.itv_is_shift and calendar._itv_expected_hours(day))
        return LegacyEmployeeSettings(
            day_hours_by_date=by_date,
            schedule_type=employee.itv_schedule_type or None,
            day_hours=employee.itv_day_hours or None,
            week_hours=employee.itv_week_hours or None,
            auto_pause=employee.itv_auto_pause,
            ignore_uhf=employee.itv_ignore_uhf,
        )

    @api.model
    def _legacy_holidays(self, employee):
        holidays = self.env['resource.calendar.leaves'].sudo().search([
            ('resource_id', '=', False), ('holiday_id', '=', False), ('company_id', 'in', [employee.company_id.id, False]),
        ])
        return [LegacyHoliday(date_from=holiday.date_from, date_to=holiday.date_to) for holiday in holidays]

    @api.model
    def _legacy_leaves(self, employee):
        # Colonne « Congé » : tous les congés, sauf les jours de repos qui ont leur propre colonne.
        domain = [('employee_id', '=', employee.id)]
        rest_type = self.env.ref('itv_zk_attendance.leave_type_rest_day', raise_if_not_found=False)
        if rest_type:
            domain.append(('holiday_status_id', '!=', rest_type.id))
        leaves = self.env['hr.leave'].sudo().with_context(active_test=False).search(domain)
        return [LegacyLeave(id=leave.id, date_from=leave.request_date_from, date_to=leave.request_date_to) for leave in leaves]

    @api.model
    def _legacy_overtime_rows(self, employee, start, end):
        """Heures déclarées par jour (colonnes déclaré, 25 %, 50 %, 100 %) : lignes mises en circuit ou validées."""
        lines = self.env['hr.attendance.overtime.line'].sudo().search([
            ('employee_id', '=', employee.id), ('date', '>=', start), ('date', '<=', end), ('itv_state', 'in', DECLARED_STATES),
        ])
        rows = {}
        for day, day_lines in lines.grouped('date').items():
            by_rate = {rate: sum(day_lines.filtered(lambda line, rate=rate: line.itv_rate == rate).mapped('duration'))
                       for rate in ('25', '50', '100')}
            rows[day] = [LegacyOvertimeRow(hs_corrige=sum(day_lines.mapped('duration')),
                                           hs_25=by_rate['25'], hs_50=by_rate['50'], hs_100=by_rate['100'])]
        return rows

    @api.model
    def _rest_days(self, employee, start, end):
        rest_type = self.env.ref('itv_zk_attendance.leave_type_rest_day', raise_if_not_found=False)
        if not rest_type:
            return set()
        leaves = self.env['hr.leave'].sudo().search([
            ('employee_id', '=', employee.id), ('holiday_status_id', '=', rest_type.id), ('state', 'in', ACTIVE_LEAVE_STATES),
            ('request_date_from', '<=', end), ('request_date_to', '>=', start),
        ])
        days = set()
        for leave in leaves:
            day = max(leave.request_date_from, start)
            while day <= min(leave.request_date_to, end):
                days.add(day)
                day += timedelta(days=1)
        return days

    @api.model
    def _legacy_day_vals(self, day):
        row = day.overtime_row
        vals = {'lg_%s' % name: _hours(getattr(day, name)) for name in LEGACY_DURATIONS}
        vals.update({
            'lg_error': False,
            'lg_punch_count': day.punch_count,
            'lg_clean_count': day.clean_count,
            'lg_carried_count': day.carried_from_next_day,
            'lg_first_punch': day.first_punch.strftime('%Y-%m-%d %H:%M:%S') if day.first_punch else False,
            'lg_last_punch': day.last_punch.strftime('%Y-%m-%d %H:%M:%S') if day.last_punch else False,
            'lg_first_punch_id': day.first_punch_id or False,
            'lg_last_punch_id': day.last_punch_id or False,
            'lg_anomalies': ",".join(day.anomalies) or False,
            'lg_presence_anomaly': 't' in day.anomalies,
            'lg_door_anomaly': day.door_anomaly,
            'lg_detected_present': day.detected_present,
            'lg_total_hs25': _hours(day.hs25_raw) + (row.hs_25 if row else 0.0),
            'lg_total_hs_declare': row.hs_corrige if row else 0.0,
            'lg_total_hs50': row.hs_50 if row else 0.0,
            'lg_total_hs100': row.hs_100 if row else 0.0,
            'lg_hs50_column': (row.hs_50 if row and row.hs_50 else _hours(day.hs50)),
            'lg_worked_day': 1 if day.punch_count else 0,
            'lg_absent_day': 0 if day.punch_count else 1,
            'is_holiday': day.holiday,
            'has_leave': bool(day.leave_ids),
            'has_manual_overtime': day.has_overtime_row,
        })
        return vals

    @api.model
    def _legacy_empty_vals(self):
        vals = {'lg_%s' % name: 0.0 for name in LEGACY_DURATIONS}
        vals.update({
            'lg_punch_count': 0, 'lg_clean_count': 0, 'lg_carried_count': 0,
            'lg_first_punch': False, 'lg_last_punch': False, 'lg_first_punch_id': False, 'lg_last_punch_id': False,
            'lg_anomalies': False, 'lg_presence_anomaly': False, 'lg_door_anomaly': False, 'lg_detected_present': False,
            'lg_total_hs25': 0.0, 'lg_total_hs_declare': 0.0, 'lg_total_hs50': 0.0, 'lg_total_hs100': 0.0,
            'lg_hs50_column': 0.0, 'lg_worked_day': 0, 'lg_absent_day': 0,
            'is_holiday': False, 'has_leave': False, 'has_manual_overtime': False,
        })
        return vals

    # -- Présences -----------------------------------------------------------------------------

    @api.model
    @api.model
    def _itv_day_for(self, employee, moment):
        """Journée de pointage correspondant à un instant UTC, créée au besoin."""
        if not employee or not moment:
            return self.browse()
        local = utc_to_local(moment, employee.tz or DEFAULT_TZ)
        date = local.date()
        day = self.search([('employee_id', '=', employee.id), ('date', '=', date)], limit=1)
        if not day:
            day = self.create({'employee_id': employee.id, 'date': date})
            # La journée entre dans la file : ses chiffres seront calculés au prochain passage.
            self.env['itv.attendance.dirty']._enqueue([(employee.id, date)])
        return day

    def _sync_attendances(self, employee, start, end):
        """Une présence par journée travaillée, du premier au dernier pointage retenu par le calcul historique.

        Les chiffres restent ceux du calcul historique : la présence ne sert qu'aux écrans natifs.
        """
        days = self.search([('employee_id', '=', employee.id), ('date', '>=', start), ('date', '<=', end)], order='date')
        Attendance = self.env['hr.attendance'].sudo().with_context(itv_attendance_sync=True, tracking_disable=True)
        existing = {attendance.itv_day_id: attendance for attendance in Attendance.search([('itv_day_id', 'in', days.ids)])}
        stale, creations = Attendance, []
        for day in days:
            vals = day._attendance_vals()
            attendance = existing.get(day, Attendance)
            if attendance and attendance.itv_manual_override:
                # Ligne corrigée à la main : elle garde ses heures, le calcul reste visible à côté.
                attendance._itv_store_computed(vals)
                continue
            if attendance and vals and (attendance.check_in, attendance.check_out) == (vals['check_in'], vals['check_out']):
                continue
            # Recréée plutôt que déplacée : déplacer une à une des présences voisines les ferait se chevaucher.
            stale |= attendance
            if vals:
                creations.append((day, vals))
        stale.unlink()
        conflicts = self.browse()
        if creations and not self._attempt(lambda: Attendance.create([vals for _day, vals in creations])):
            for day, vals in creations:
                if not self._attempt(lambda vals=vals: Attendance.create(vals)):
                    conflicts |= day
        (days - conflicts).filtered('attendance_conflict').write({'attendance_conflict': False})
        (conflicts - conflicts.filtered('attendance_conflict')).write({'attendance_conflict': True})
        if conflicts:
            _logger.info("Présences non reportées pour %s (chevauchement) : %s",
                         employee.display_name, ", ".join(str(day.date) for day in conflicts))
        days._relink_overtime()

    def _attendance_vals(self):
        """Une présence par journée : du premier au dernier pointage retenu, sinon un repère d'une seconde à midi.

        Le repère garde une ligne par jour dans Présences (absence, pointage impair, mois non calculé).
        """
        self.ensure_one()
        first, last = self.lg_first_punch_id, self.lg_last_punch_id
        usable = not self.lg_error and not self.lg_presence_anomaly and first and last and last.punch_time > first.punch_time
        if usable:
            check_in, check_out = first.punch_time, last.punch_time
        elif first:
            # Pointages présents mais non appariés (impairs, mois en erreur) : on garde les heures réelles
            # plutôt qu'un repère à midi, sinon l'écran affiche 12:00 pour des journées réellement pointées.
            check_in = first.punch_time
            check_out = last.punch_time if last and last.punch_time > check_in else check_in + timedelta(seconds=1)
        else:
            check_in = local_to_utc(datetime.combine(self.date, time(12, 0)), self.employee_id.tz or DEFAULT_TZ)
            check_out = check_in + timedelta(seconds=1)
        return {
            'employee_id': self.employee_id.id,
            'check_in': check_in,
            'check_out': check_out,
            'in_mode': 'technical',
            'out_mode': 'technical',
            'itv_day_id': self.id,
            'itv_is_marker': not usable,
            'itv_computed_check_in': check_in,
            'itv_computed_check_out': check_out,
        }

    def _relink_overtime(self):
        """Présences rattache une heure supplémentaire à la présence qui commence à la même heure : on suit la présence recréée."""
        lines = self.env['hr.attendance.overtime.line'].sudo().search([('itv_day_id', 'in', self.ids)])
        if not lines:
            return
        attendances = self.env['hr.attendance'].sudo().search([('itv_day_id', 'in', self.ids)])
        by_day = {attendance.itv_day_id: attendance for attendance in attendances}
        for line in lines:
            attendance = by_day.get(line.itv_day_id)
            times = (attendance.check_in, attendance.check_out) if attendance else (False, False)
            if (line.time_start or False, line.time_stop or False) != times:
                line.write({'time_start': times[0], 'time_stop': times[1]})
        lines._itv_refresh_attendances(attendances)

    @api.model
    def _attempt(self, function):
        try:
            with self.env.cr.savepoint():
                function()
        except ValidationError:
            return False
        return True

    def _backend_timezone(self):
        backend = self.env['itv.zk.backend'].sudo().with_context(active_test=False).search(
            [('company_id', '=', self.employee_id.company_id.id)], order='kind, id', limit=1)
        return backend, (backend.timezone or DEFAULT_TZ)

    # -- Actions ---------------------------------------------------------------------------------

    def action_recompute_days(self):
        self.check_access('read')
        for employee, days in self.grouped('employee_id').items():
            self.sudo()._recompute_days(employee, days.mapped('date'))
        return True

    def action_propose_overtime(self):
        days = self.filtered(lambda day: not day.lg_error and not day.overtime_line_ids and (day.lg_hs25 > 0 or day.lg_hs50 > 0))
        if not days:
            raise UserError(_("Aucune journée sélectionnée n'a d'heures supplémentaires à proposer."))
        vals_list = []
        for day in days:
            attendance = day.attendance_ids[:1]
            sunday = day.lg_hs50 > 0
            vals_list.append({
                'employee_id': day.employee_id.id,
                'date': day.date,
                'duration': day.lg_hs50 if sunday else day.lg_hs25,
                'itv_rate': '50' if sunday else '25',
                'itv_state': 'submitted',
                'itv_day_id': day.id,
                'time_start': attendance.check_in or False,
                'time_stop': attendance.check_out or False,
            })
        self.env['hr.attendance.overtime.line'].create(vals_list)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _("Heures supplémentaires proposées"),
                'message': _("%s journée(s) envoyée(s) en validation.", len(days)),
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }

    def action_open_punches(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('itv_zk_connector.itv_zk_punch_action')
        action.update({
            'name': _("Pointages de %(employee)s le %(date)s", employee=self.employee_id.name, date=format_date(self.env, self.date)),
            'domain': [('employee_id', '=', self.employee_id.id), ('punch_date', 'in', [self.date, self.date + timedelta(days=1)])],
            'context': {'search_default_group_day': 1},
        })
        return action

    def action_add_punch(self):
        self.ensure_one()
        _backend, tz = self._backend_timezone()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Ajouter un pointage"),
            'res_model': 'itv.attendance.punch.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {
                'default_day_id': self.id,
                'default_punch_time': fields.Datetime.to_string(local_to_utc(datetime.combine(self.date, time(8, 0)), tz)),
            },
        }

    def action_new_leave(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Nouveau congé"),
            'res_model': 'hr.leave',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {
                'default_employee_id': self.employee_id.id,
                'default_request_date_from': fields.Date.to_string(self.date),
                'default_request_date_to': fields.Date.to_string(self.date),
            },
        }

    def action_toggle_rest_day(self):
        self.ensure_one()
        self.check_access('read')
        rest_type = self.env.ref('itv_zk_attendance.leave_type_rest_day')
        Leave = self.env['hr.leave'].sudo()
        leaves = Leave.search([
            ('employee_id', '=', self.employee_id.id), ('holiday_status_id', '=', rest_type.id), ('state', 'in', ACTIVE_LEAVE_STATES),
            ('request_date_from', '<=', self.date), ('request_date_to', '>=', self.date),
        ])
        if leaves:
            for leave in leaves:
                leave._force_cancel(_("Jour de repos retiré depuis Pointage par employé."), notify_responsibles=False)
            self.sudo().is_rest_day = False
            return True
        try:
            with self.env.cr.savepoint():
                Leave.create({
                    'employee_id': self.employee_id.id,
                    'holiday_status_id': rest_type.id,
                    'request_date_from': self.date,
                    'request_date_to': self.date,
                })
        except ValidationError as exc:
            raise UserError(_("Jour de repos impossible pour %(employee)s le %(date)s :\n%(reason)s",
                              employee=self.employee_id.name, date=format_date(self.env, self.date), reason=exc.args[0])) from exc
        self.sudo().is_rest_day = True
        return True

    def action_reopen_anomaly(self):
        self.check_access('read')
        self.sudo().filtered('anomaly_resolution').write({'anomaly_resolution': False, 'anomaly_note': False})
        return True
