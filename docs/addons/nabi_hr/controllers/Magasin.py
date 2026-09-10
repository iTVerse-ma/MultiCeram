# -*- coding: utf-8 -*-

from odoo import http
from odoo.http import request
from odoo.exceptions import ValidationError

from datetime import date, timedelta
import requests

import qrcode
import base64
from io import BytesIO

class ZkPortalMagasin(http.Controller):

    @http.route(['/my/magasin','/my/magasin/<int:page>'], type='http', auth='public', website=True)
    def portal_magasin(self, page=1,matricule=None,date_from=None,date_to=None,**kw):
        BASE_URL    = request.env['ir.config_parameter'].sudo().get_param('zk.server')
        API_URL     = f"{BASE_URL}iclock/api/transactions/"
        DEVICE_SN   = request.env['ir.config_parameter'].sudo().get_param('zk.magasin.terminal') or "NYU7243300081"
        API_USER    = request.env['ir.config_parameter'].sudo().get_param('zk.user')
        API_PASS    = request.env['ir.config_parameter'].sudo().get_param('zk.password')


        
        # USER            = request.env['ir.config_parameter'].sudo().get_param('zk.user')
        # PASSWORD        = request.env['ir.config_parameter'].sudo().get_param('zk.password')
        # AUTH            = (USER, PASSWORD)

        params = {
            "terminal_sn": DEVICE_SN,
            "page_size":50,
            "limit": 50,
            "ordering": "-punch_time",
            "page":page
        }
        if matricule:
            params['emp_code']=matricule
        
        if date_from:
            params['start_time'] = date_from
        if date_from:
            params['end_time'] = date_to

        # --- Call BioTime REST API
        res = requests.get(API_URL, params=params, auth=(API_USER, API_PASS))
        data = res.json().get("data", [])
        next = res.json().get("next", False)
        prev =  res.json().get("previous", False) 

        punches = []
        for p in data:
            if not p["first_name"]:
                continue
            emp_code = p["emp_code"]
            # Generate QR code as base64
            qr = qrcode.make(emp_code)
            buffer = BytesIO()
            qr.save(buffer, format="PNG")
            qr_b64 = base64.b64encode(buffer.getvalue()).decode()
            punches.append({
                "emp_code": emp_code,
                "emp_name": f'{p["first_name"]} {p["last_name"]}',
                "punch_time": p["punch_time"],
                "qr_code": qr_b64,
                
            })

        return request.render("nabi_hr.portal_magasin", {"punches": punches,"page":page,
                "next" : next ,
                "prev" : prev,
                 'matricule' : matricule,
                 'date_from' : date_from,
                 'date_to' : date_to,

                 
                  })

    