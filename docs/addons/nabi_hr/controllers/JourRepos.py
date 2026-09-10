# -*- coding: utf-8 -*-

from odoo import http,_,fields
from odoo.http import request
from odoo.tools import format_date

from odoo.exceptions import ValidationError
from dateutil.relativedelta import relativedelta

from datetime import date, timedelta,datetime
import requests


from collections import namedtuple

class DotDict(dict):
    def __getattr__(self, key):
        value = self.get(key)
        if isinstance(value, dict):
            return DotDict(value)
        if isinstance(value, list):
            return [DotDict(v) if isinstance(v, dict) else v for v in value]
        return value

    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__

def dotify(obj):
    if isinstance(obj, dict):
        return DotDict({k: dotify(v) for k, v in obj.items()})
    elif isinstance(obj, list):
        return [dotify(i) for i in obj]
    return obj


def is_host_reachable(host, AUTH, timeout=3):
    try:
        with requests.get(f"{host}att/api/", auth=AUTH, params={}, timeout=timeout):
            return True
    except Exception as e:
        return False

class JourRepos(http.Controller):

    @http.route('/my/HeureSupp/Validation', type='http', auth='user', website=True,csrf=False)
    def portal_reste_days(self, start_day = None, end_day=None, emp_id=0,department_ids='',**kw):
        if start_day:
            start_day = fields.Date.from_string(start_day) 
        else :
            start_day = datetime.today().date() + relativedelta(months=-1)
        
        if end_day:
            end_day = fields.Date.from_string(end_day) 
        else:
            end_day = datetime.today().date()

        

        domain = []
        employee = request.env['hr.employee'].search([('active','in',(True,False)),('barcode','=',emp_id)])
        jf =  request.env['resource.calendar.leaves'].search([('resource_id','=',False),
                                                              '|','&',('date_from','>=',start_day),('date_from','<=',end_day),
                                                              '&',('date_to','>=',start_day),('date_to','<=',end_day)])

        
        if department_ids:
            department_ids = list(map(int,department_ids.split(',')))
            domain += [('x_employee_id.department_id' ,'in',department_ids)]
        
        jrs = request.env["x_jour_repos"].search(domain)
        
        return request.render("nabi_hr.portal_validation_heures_supp",  dotify({
            'format_date'   : lambda x:format_date(request.env,value=x,lang_code='fr_FR',date_format='EEE').capitalize(),
            '_'             : _,
            'departments'     : request.env['hr.department'].search([]), 
            'portal_punches': jrs,
            'emp_id'        : emp_id,
            'start_day'     : start_day,
            'end_day'       : end_day,
            'department_ids'  : department_ids,
            "domain"        : domain,
            
            "kw"            : kw,
            "jf"            : jf,
            "employee"      : employee,
            "emp_zkid"      : employee.zk_id,

            
            





            
        }))

