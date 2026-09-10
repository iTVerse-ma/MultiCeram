# -*- coding: utf-8 -*-
# from odoo import http





from odoo import http
from odoo.http import request
from odoo.exceptions import ValidationError

from datetime import date, timedelta
import requests


class PortalLeaves(http.Controller):

    
    @http.route(['/my/leaves', '/my/leaves/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_leaves(self, page=1, **kw):
        leaves = request.env['hr.leave'].sudo().search([('employee_id.user_id','=',request.env.user.id)])
        return request.render("nabi_hr.portal_my_leaves", {
            'leaves': leaves,
        })

    @http.route(['/my/leaves/news'], type='http', auth="user", website=True, methods=['GET', 'POST'])
    def portal_new_leave(self, **post):
        if post:
            employee = request.env['hr.employee'].search([('user_id','=',request.env.user.id)], limit=1)
            request.env['hr.leave'].sudo().create({
                'holiday_status_id': int(post.get('holiday_status_id')),
                'employee_id': employee.id,
                'request_date_from': post.get('date_from'),
                'request_date_to': post.get('date_to'),
                'name': post.get('reason'),
            })
            return request.redirect('/my/leaves')
        return request.render("nabi_hr.portal_new_leave_form", {})


    @http.route(['/my/leaves/new'], type='http', auth="user", website=True, methods=['GET', 'POST'])
    def portal_new_leave(self, **post):
        error = False
        if post:
            try:
                employee = request.env['hr.employee'].search([('user_id','=',request.env.user.id)], limit=1)
                request.env['hr.leave'].sudo().create({
                    'holiday_status_id': int(post.get('holiday_status_id')),
                    'employee_id': employee.id,
                    'request_date_from': post.get('date_from'),
                    'request_date_to': post.get('date_to'),
                    'name': post.get('reason'),
                })
                return request.redirect('/my/leaves')
            except ValidationError as e:
                error = str(e.name) if hasattr(e, "name") else str(e)

        return request.render("nabi_hr.portal_new_leave_form", {
            'error': error,
        })


    @http.route(['/my/leaves/action/<string:action>'], 
                type='http', auth="user", website=True, methods=['POST'])
    def portal_leave_action(self, action, leave_id,**kw):

        leave = request.env['hr.leave'].sudo().browse(int(leave_id))
        user = request.env.user

        if not leave.exists():
            return request.redirect('/my/leaves')

        # Manager or HR check
        is_manager = user.has_group("hr_holidays.group_hr_holidays_manager")
        is_officer = user.has_group("hr_holidays.group_hr_holidays_user")

        try:
            if action == "refuse":
                leave.action_refuse()
            elif action == "reset":
                leave.action_reset_confirm()
            elif action == "cancel":
                leave.action_cancel()
            elif action == "validate_manager" and is_manager:
                leave.action_approve()
            elif action == "validate_hr" and is_officer:
                leave.action_validate()
        except Exception as e:
            return request.render("nabi_hr.portal_my_leaves", {
                "leaves": request.env['hr.leave'].sudo().search([]),
                "error": str(e),
            })

        return request.redirect('/my/leaves')


