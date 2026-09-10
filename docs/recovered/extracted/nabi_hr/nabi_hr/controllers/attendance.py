# -*- coding: utf-8 -*-

from odoo import http,fields
from odoo.http import request
from datetime import date, timedelta

class HrAttendancePortal(http.Controller):

    @http.route(['/my/attendance'], type='http', auth='user', website=True)
    def portal_attendance(self, **kw):
        today = date.today()
        start = today - timedelta(days=7)
        end = today + timedelta(days=1)

        # récupérer les employés
        employees = request.env['hr.employee'].sudo().search([])

        # récupérer les pointages de la semaine
        punches = {}
        for emp in employees:
            punches[emp.id] = {}
            for rec in request.env['hr.attendance'].sudo().search([
                ('employee_id', '=', emp.id),
                ('check_in', '>=', start),
                ('check_in', '<=', end),
            ]):
                day = rec.check_in.date()
                punches[emp.id].setdefault(day, []).append(rec)

        return request.render("base.portal_attendance", {
            'employees': employees,
            'punches': punches,
            'days': [start + timedelta(days=i) for i in range((end-start).days+1)],
        })

    @http.route(['/my/attendance/action'], type='http', auth='user', methods=['POST'], website=True, csrf=False)
    def portal_attendance_action(self, **post):
        emp_id = int(post.get('employee_id'))
        action = post.get('action')
        day_str = post.get('day')
        day = fields.Date.from_string(day_str)

        emp = request.env['hr.employee'].sudo().browse(emp_id)

        if action == 'manual':
            # créer un pointage manuel
            request.env['hr.attendance'].sudo().create({
                'employee_id': emp.id,
                'check_in': day,
                'check_out': day + timedelta(hours=8),
            })
        elif action == 'delete_repeated':
            # supprimer doublons
            recs = request.env['hr.attendance'].sudo().search([('employee_id','=',emp.id), ('check_in','>=',day), ('check_in','<',day+timedelta(days=1))])
            if len(recs) > 1:
                recs[1:].unlink()
        elif action == 'we':
            # créer WE day
            request.env['hr.leave'].sudo().create({
                'employee_id': emp.id,
                'holiday_status_id': request.env['hr.leave.type'].sudo().search([('name','=','Reste Day')], limit=1).id,
                'request_date_from': day,
                'request_date_to': day,
            })
        elif action == 'holiday':
            # créer congé férié
            request.env['hr.leave'].sudo().create({
                'employee_id': emp.id,
                'holiday_status_id': request.env['hr.leave.type'].sudo().search([('name','=','Férié')], limit=1).id,
                'request_date_from': day,
                'request_date_to': day,
            })

        return request.redirect('/my/attendance')