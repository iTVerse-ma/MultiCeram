# -*- coding: utf-8 -*-
"""Pages du portail employé.

L'employé est toujours déduit de l'utilisateur connecté (`hr.employee.user_id`), jamais d'un
paramètre d'URL. Les accès aux modèles RH se font en `sudo()` **après** ce filtrage, car un
utilisateur portail n'a aucun droit dessus.
"""
import logging
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import _, fields, http
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request

from odoo.addons.portal.controllers.portal import CustomerPortal

logger = logging.getLogger(__name__)

# Une demande encore « à approuver » peut être retirée par l'employé ; après, c'est aux RH.
CANCELABLE_STATES = ('confirm',)
DAY_TOTAL_FIELDS = ('lg_heures', 'lg_heures25', 'lg_hs', 'lg_worked_day', 'lg_absent_day')


class ItvHrPortal(CustomerPortal):

    # ------------------------------------------------------------------ outils

    def _itv_employee(self, raise_if_missing=True):
        employee = request.env['hr.employee'].sudo().search(
            [('user_id', '=', request.env.user.id)], limit=1)
        if not employee and raise_if_missing:
            raise AccessError(_("Aucun employé n'est rattaché à votre compte. Contactez le service du personnel."))
        return employee

    def _itv_month_bounds(self, year=None, month=None):
        """Mois demandé (ou mois courant), borné au mois où commencent les données."""
        today = fields.Date.context_today(request.env.user)
        try:
            first = date(int(year), int(month), 1)
        except (TypeError, ValueError):
            first = today.replace(day=1)
        return first, first + relativedelta(months=1, days=-1)

    def _prepare_portal_layout_values(self):
        values = super()._prepare_portal_layout_values()
        employee = self._itv_employee(raise_if_missing=False)
        values['itv_employee'] = employee
        if employee:
            values['itv_leave_count'] = request.env['hr.leave'].sudo().search_count(
                [('employee_id', '=', employee.id)])
            # Ne comptent que les anomalies que les RH ont envoyées : l'employé doit les expliquer.
            values['itv_anomaly_count'] = request.env['itv.attendance.day'].sudo().search_count(
                [('employee_id', '=', employee.id), ('itv_portal_state', '=', 'sent')])
        return values

    # -------------------------------------------------------------- pointages

    @http.route(['/my/pointages', '/my/pointages/<int:year>/<int:month>'], type='http', auth='user', website=True)
    def itv_portal_days(self, year=None, month=None, **kwargs):
        employee = self._itv_employee()
        start, end = self._itv_month_bounds(year, month)
        days = request.env['itv.attendance.day'].sudo().search(
            [('employee_id', '=', employee.id), ('date', '>=', start), ('date', '<=', end)], order='date')
        previous_month = start - relativedelta(months=1)
        next_month = start + relativedelta(months=1)
        values = self._prepare_portal_layout_values()
        values.update(
            page_name='itv_days',
            employee=employee,
            days=days,
            month_start=start,
            previous_month=previous_month,
            next_month=next_month,
            next_allowed=next_month <= fields.Date.context_today(request.env.user).replace(day=1),
            totals={name: sum(days.mapped(name)) for name in DAY_TOTAL_FIELDS},
        )
        return request.render('itv_hr_portal.portal_my_days', values)

    # -------------------------------------------------------------- anomalies

    @http.route(['/my/anomalies'], type='http', auth='user', website=True)
    def itv_portal_anomalies(self, **kwargs):
        employee = self._itv_employee()
        # L'employé ne voit que les anomalies qui lui ont été envoyées.
        days = request.env['itv.attendance.day'].sudo().search([
            ('employee_id', '=', employee.id), ('itv_portal_state', '!=', False),
        ], order='date desc', limit=200)
        values = self._prepare_portal_layout_values()
        values.update(page_name='itv_anomalies', employee=employee, days=days, message=kwargs.get('message'))
        return request.render('itv_hr_portal.portal_my_anomalies', values)

    @http.route(['/my/anomalies/<int:day_id>/justifier'], type='http', auth='user',
                methods=['POST'], csrf=True, website=True)
    def itv_portal_anomaly_justify(self, day_id, **post):
        employee = self._itv_employee()
        day = request.env['itv.attendance.day'].sudo().browse(day_id).exists()
        # Contrôle d'appartenance : on ne justifie que ses propres journées.
        if not day or day.employee_id != employee:
            raise AccessError(_("Cette journée ne vous appartient pas."))
        reason = (post.get('reason') or '').strip()
        if not reason:
            return request.redirect('/my/anomalies?message=explication_vide')
        if day.itv_portal_state != 'sent':
            return request.redirect('/my/anomalies?message=deja_traitee')
        day._itv_portal_submit(reason[:500])
        return request.redirect('/my/anomalies?message=explication_envoyee')

    # ------------------------------------------------ heures supplémentaires

    @http.route(['/my/heures-supplementaires'], type='http', auth='user', website=True)
    def itv_portal_overtime(self, **kwargs):
        employee = self._itv_employee()
        lines = request.env['hr.attendance.overtime.line'].sudo().search(
            [('employee_id', '=', employee.id), ('itv_state', '!=', False)], order='date desc')
        months = {}
        for line in lines:
            months.setdefault(line.date.replace(day=1), request.env['hr.attendance.overtime.line'].sudo())
            months[line.date.replace(day=1)] |= line
        values = self._prepare_portal_layout_values()
        values.update(
            page_name='itv_overtime', employee=employee, lines=lines,
            months=sorted(months.items(), reverse=True),
            to_declare=lines.filtered(lambda line: line.itv_declaration_state == 'asked'),
            validated_total=sum(lines.filtered(lambda l: l.itv_state == 'validated_2').mapped('duration')),
            pending_total=sum(lines.filtered(lambda l: l.itv_state in ('submitted', 'validated_1')).mapped('duration')),
        )
        return request.render('itv_hr_portal.portal_my_overtime', values)

    @http.route(['/my/heures-supplementaires/<int:line_id>/declarer'], type='http', auth='user',
                methods=['POST'], csrf=True, website=True)
    def itv_portal_overtime_declare(self, line_id, **post):
        """L'employé déclare ses heures : il répond sans avoir vu le calcul."""
        employee = self._itv_employee()
        line = request.env['hr.attendance.overtime.line'].sudo().browse(line_id).exists()
        if not line or line.employee_id != employee or line.itv_declaration_state != 'asked':
            return request.redirect('/my/heures-supplementaires')
        try:
            hours = float((post.get('hours') or '0').replace(',', '.'))
        except ValueError:
            hours = -1
        if hours < 0:
            return request.redirect('/my/heures-supplementaires?erreur=heures')
        # Toute la journée de l'employé suit la même déclaration.
        same_day = line.search([('employee_id', '=', employee.id), ('date', '=', line.date),
                                ('itv_declaration_state', '=', 'asked')])
        same_day._itv_portal_declare(hours, post.get('note'))
        return request.redirect('/my/heures-supplementaires')

    # ----------------------------------------------------------------- congés

    def _itv_portal_leave_types(self):
        return request.env['hr.leave.type'].sudo().search(
            [('active', '=', True), ('itv_portal_visible', '=', True)], order='name')

    @http.route(['/my/conges'], type='http', auth='user', website=True)
    def itv_portal_leaves(self, **kwargs):
        employee = self._itv_employee()
        leaves = request.env['hr.leave'].sudo().search(
            [('employee_id', '=', employee.id)], order='request_date_from desc')
        values = self._prepare_portal_layout_values()
        values.update(page_name='itv_leaves', employee=employee, leaves=leaves,
                      cancelable_states=CANCELABLE_STATES, message=kwargs.get('message'))
        return request.render('itv_hr_portal.portal_my_leaves', values)

    @http.route(['/my/conges/nouveau'], type='http', auth='user', methods=['GET', 'POST'], csrf=True, website=True)
    def itv_portal_leave_new(self, **post):
        employee = self._itv_employee()
        values = self._prepare_portal_layout_values()
        values.update(page_name='itv_leaves', employee=employee,
                      leave_types=self._itv_portal_leave_types(), post=post)
        if request.httprequest.method == 'GET':
            return request.render('itv_hr_portal.portal_leave_form', values)

        error = self._itv_create_leave(employee, post)
        if error:
            values['error'] = error
            return request.render('itv_hr_portal.portal_leave_form', values)
        return request.redirect('/my/conges?message=demande_enregistree')

    def _itv_create_leave(self, employee, post):
        """Crée la demande ; renvoie un message d'erreur lisible, ou None."""
        leave_type = self._itv_portal_leave_types().filtered(
            lambda record: str(record.id) == (post.get('leave_type_id') or ''))
        date_from = post.get('date_from') or ''
        date_to = post.get('date_to') or date_from
        if not leave_type:
            return _("Choisissez un type de congé.")
        try:
            start = fields.Date.to_date(date_from)
            stop = fields.Date.to_date(date_to)
        except (TypeError, ValueError):
            return _("Dates invalides.")
        if not start or not stop:
            return _("Indiquez les dates de début et de fin.")
        if stop < start:
            return _("La date de fin est antérieure à la date de début.")
        try:
            with request.env.cr.savepoint():
                request.env['hr.leave'].sudo().create({
                    'employee_id': employee.id,
                    'holiday_status_id': leave_type.id,
                    'request_date_from': start,
                    'request_date_to': stop,
                    'name': (post.get('reason') or '').strip()[:200] or leave_type.display_name,
                })
        except (UserError, ValidationError) as error:
            return error.args[0] if error.args else _("Demande refusée.")
        except Exception:  # noqa: BLE001 — l'employé voit un message neutre, la cause part dans le journal
            logger.exception("Portail : création de congé refusée pour l'employé %s", employee.id)
            return _("La demande n'a pas pu être enregistrée. Contactez le service du personnel.")
        return None

    @http.route(['/my/conges/<int:leave_id>/annuler'], type='http', auth='user', methods=['POST'], csrf=True, website=True)
    def itv_portal_leave_cancel(self, leave_id, **post):
        employee = self._itv_employee()
        leave = request.env['hr.leave'].sudo().browse(leave_id).exists()
        # Contrôle d'appartenance : une demande d'un autre employé n'est jamais touchée.
        if not leave or leave.employee_id != employee:
            raise AccessError(_("Cette demande ne vous appartient pas."))
        if leave.state not in CANCELABLE_STATES:
            return request.redirect('/my/conges?message=annulation_impossible')
        leave.unlink()
        return request.redirect('/my/conges?message=demande_annulee')
