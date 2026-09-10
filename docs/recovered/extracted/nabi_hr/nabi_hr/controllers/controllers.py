# -*- coding: utf-8 -*-
# from odoo import http


# class NabiHr(http.Controller):
#     @http.route('/nabi_hr/nabi_hr', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/nabi_hr/nabi_hr/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('nabi_hr.listing', {
#             'root': '/nabi_hr/nabi_hr',
#             'objects': http.request.env['nabi_hr.nabi_hr'].search([]),
#         })

#     @http.route('/nabi_hr/nabi_hr/objects/<model("nabi_hr.nabi_hr"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('nabi_hr.object', {
#             'object': obj
#         })


from odoo import http
from odoo.http import request
from odoo.exceptions import ValidationError

from datetime import date, timedelta


class PortalLeaves(http.Controller):

    @http.route(['/my/leaves', '/my/leaves/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_leaves(self, page=1, **kw):
        leaves = request.env['hr.leave'].sudo().search([('employee_id.user_id','=',request.env.user.id)])
        return request.render("base.portal_my_leaves", {
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
        return request.render("base.portal_new_leave_form", {})


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

        return request.render("base.portal_new_leave_form", {
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
            return request.render("base.portal_my_leaves", {
                "leaves": request.env['hr.leave'].sudo().search([]),
                "error": str(e),
            })

        return request.redirect('/my/leaves')



class ResteDayPortal(http.Controller):


    @http.route('/my/reste-days', type='http', auth='user', website=True)
    def portal_reste_days(self, **kw):
        today = date.today()
        current_week = today.isocalendar()[1]
        employee = request.env.user.employee_id
        reste_type = request.env['hr.leave.type'].sudo().search([('name', '=', 'Reste Day')], limit=1)

        # récupérer les jours déjà enregistrés
        existing_days = {}
        if employee and reste_type:
            leaves = request.env['hr.leave'].sudo().search([
                ('employee_id', '=', employee.id),
                ('holiday_status_id', '=', reste_type.id),
            ])
            for leave in leaves:
                wk = leave.request_date_from.isocalendar()[1]
                existing_days.setdefault(wk,[])
                existing_days[wk].append( leave.request_date_from.strftime('%Y-%m-%d'))

        weeks = []
        for offset in range(-2, 9):  # n-2 → n+8
            monday = today + timedelta(weeks=offset, days=-today.weekday())
            sunday = monday + timedelta(days=6)
            wk_num = monday.isocalendar()[1]

            days = []
            for i in range(7):
                d = monday + timedelta(days=i)
                iso = d.strftime("%Y-%m-%d")
                days.append({
                    "date": iso,
                    "label": d.strftime("%d"),  # juste le jour du mois
                            "day_of_week": d.strftime("%a"),  # Mon, Tue, etc.

                    "selected": existing_days.get(wk_num) and iso in existing_days.get(wk_num),

                    "is_today": (d == today),
                })
            weeks.append({
                "week_num": wk_num,
                "start": monday,
                "end": sunday,
                "days": days,
                "is_current": (wk_num == current_week),
            })

        return request.render("base.portal_reste_days", {
            "weeks": weeks,
            "message": kw.get("message"),
        })

    @http.route('/my/toggle-reste-day', type='http', auth='user', methods=["POST"], website=True, csrf=False)
    def toggle_reste_day(self, **post):
        employee = request.env.user.employee_id
        date_str = post.get("reste_date")
        d = date.fromisoformat(date_str)
        wk = d.isocalendar()[1]
        reste_type = request.env['hr.leave.type'].sudo().search([('name', '=', 'Reste Day')], limit=1)

        if not (employee and reste_type):
            return request.redirect("/my/reste-days?message=Erreur")

        existing = request.env['hr.leave'].sudo().search([
            ('employee_id', '=', employee.id),
            ('holiday_status_id', '=', reste_type.id),
            ('request_date_from', '>=', d - timedelta(days=d.weekday())),  # semaine courante
            ('request_date_to', '<=', d + timedelta(days=(6 - d.weekday()))),
        ])

        if existing and existing.filtered(lambda x:x.request_date_from == d):
            # toggle OFF (désélection)
            existing.filtered(lambda x:x.request_date_from == d).unlink()
            msg = f"Jour de repos {date_str} supprimé"
        else:
            # supprimer autre jour de la semaine si existe
            if existing:
                existing.unlink()

            # ajouter le jour sélectionné
            request.env['hr.leave'].sudo().create({
                "name": "Reste Day",
                "employee_id": employee.id,
                "holiday_status_id": reste_type.id,
                "request_date_from": date_str,
                "request_date_to": date_str,
            })

            # propagation aux semaines futures si pas déjà défini
            for i in range(1, 9):
                future = d + timedelta(weeks=i)
                wk_future = future.isocalendar()[1]

                already = request.env['hr.leave'].sudo().search([
                    ('employee_id', '=', employee.id),
                    ('holiday_status_id', '=', reste_type.id),
                    ('request_date_from', '>=', future - timedelta(days=future.weekday())),
                ])

                if not already:
                    request.env['hr.leave'].sudo().create({
                        "name": "Reste Day",
                        "employee_id": employee.id,
                        "holiday_status_id": reste_type.id,
                        "request_date_from": future,
                        "request_date_to": future,
                    })

            msg = f"Jour de repos {date_str} sélectionné"

        return request.redirect(f"/my/reste-days?message={msg}")