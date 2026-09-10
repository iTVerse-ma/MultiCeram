# -*- coding: utf-8 -*-

from odoo import http
from odoo.http import request
from odoo.exceptions import ValidationError

from datetime import date, timedelta
import requests


class PortalRestaurant(http.Controller):

    @http.route(['/my/restaurant', '/my/restaurant/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_restaurant(self, page=1, **kw):
        #overtimes = request.env['hr.leave'].sudo().search([('employee_id.user_id','=',request.env.user.id)])
        return request.render("nabi_hr.portal_my_restaurant", {
            'overtimes': [],
        })

    