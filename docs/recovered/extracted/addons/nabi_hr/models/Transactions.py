# -*- coding: utf-8 -*-

from odoo import models,fields, api, _
import requests,json,base64
from odoo.exceptions import UserError
from datetime import datetime, timedelta
import logging
_logger = logging.getLogger(__name__)
import datetime


class ZkTerminals(models.Model):
    _name = "zk.terminals"
    _rec_name = "alias"

    tid             = fields.Char("Id ZK")
    sn              = fields.Char("SN")
    alias           = fields.Char("alias")
    usage           = fields.Selection([('t',u'Présence'),('p','Suivi des Pause'),('r','Restaurant')],"Usage")
    last_activity   = fields.Datetime("Dernière activité")
    last_sync       = fields.Datetime("Dernière synchronisation")
    sens            = fields.Selection([('in','In'),('out','Out')] , 'Sens',default=False)
   
    
    def sync_terminals(self):
        pass
        BASE_URL,_,_,AUTH = self.env["zk.connector"]._get_connection_params()

        API = f"/iclock/api/terminals/"
        params = {}
        page = 1
        while True:
            params["page"] = page
            res = requests.get(f"{BASE_URL}{API}", auth=AUTH, params=params, timeout=60)
            if res.status_code != 200:
                raise ValueError(f"Failed to fetch terminals: {res.text}")
            data = res.json()
            tx_list = data.get("data", [])
            if not tx_list:
                break

            for tx in tx_list:
                val = {
                        'tid' : tx.get('id'),
                        'sn' : tx.get('sn'),
                        'alias' : tx.get('alias'),
                        'last_activity' : tx.get('last_activity')
                }
                if not self.search([('tid','=',tx.get('id'))]):
                    self.create(val)
                

            if not data.get("next"):
                break
            page += 1

    def sync_transaction(self):
        BASE_URL,_,_,AUTH = self.env["zk.connector"]._get_connection_params()
        API = f"/iclock/api/transactions/"
        
        for o in self:
            params = {'terminal_sn':o.sn,
                      'start_time' : min([o.last_activity or datetime.datetime.now(),o.last_sync or datetime.datetime.now(),]),
                      }
            page = 1
            tids = self.env['zk.transaction'].search([]).mapped('tid')
            while True:
                params["page"] = page
                values =[]
                res = requests.get(f"{BASE_URL}{API}", auth=AUTH, params=params, timeout=60)
                if res.status_code != 200:
                    raise ValueError(f"Failed to fetch Transactions: {res.text}")
                data = res.json()
                tx_list = data.get("data", [])
                if not tx_list:
                    break

                for tx in tx_list:
                    val = {
                        "tid"               :tx.get("id"),                
                        "emp"               :tx.get("emp"),                
                        "emp_code"          :tx.get("emp_code"),           
                        "first_name"        :tx.get("first_name"),         
                        "last_name"         :tx.get("last_name"),          
                        "punch_time"        :tx.get("punch_time"),         
                        "terminal_sn"       :tx.get("terminal_sn"),        
                        "terminal_alias"    :tx.get("terminal_alias"),     
                        "upload_time"       :tx.get("upload_time"),        
                    }


                    if not tids:
                        values.append(val)
                        
                self.env['zk.transaction'].create(val)
                self.env.cr.commit()
                            
                    

                if not data.get("next"):
                    break
                page += 1
            o.last_sync = datetime.datetime.now()
            self.env.cr.commit()







class ZkTransaction(models.Model):
    _name = "zk.transaction"

    """

<field name="tid"/>                
<field name="emp"/>                
<field name="emp_code"/>           
<field name="first_name"/>         
<field name="last_name"/>          
<field name="punch_time"/>         
<field name="terminal_sn"/>        
<field name="terminal_alias"/>     
<field name="upload_time"/>        
<field name="terminal_id"/>        
<field name="usage"/>              

    {
    "id"                    : 44434,
    "emp"                   : 2317,
    "emp_code"              : "7073",
    "first_name"            : "Shahath Thalip",
    "last_name"             : null,
    "department"            : "IT",
    "position"              : "tech",
    "punch_time"            : "2025-09-24 14:03:45",
    "punch_state"           : "0",
    "punch_state_display"   : "0",
    "verify_type"           : 1,
    "verify_type_display"   : "Fingerprint",
    "work_code"             : "0",
    "gps_location"          : "",
    "area_alias"            : "HM HBT",
    "terminal_sn"           : "TTQ5242000031",
    "temperature"           : 0.0,
    "is_mask"               : "-",
    "terminal_alias"        : "workshop",
    "upload_time"           : "2025-09-26 19:37:51"
}





    """


    tid                  = fields.Char("Transaction id")
    emp                 = fields.Char("Id employee ZK")
    emp_code            = fields.Char("Code employee ZK")
    first_name          = fields.Char("Prénom")
    last_name           = fields.Char("Nom")
    punch_time          = fields.Datetime("temps de pointage")
    terminal_sn         = fields.Char("Terminal SN")
    terminal_alias      = fields.Char("Terminal Alias")
    upload_time         = fields.Char("Temps de télechargement")
    terminal_id         = fields.Many2one("zk.terminals","Terminal", compute="_get_terminal", store=True)
    usage               = fields.Selection(string="Usage" ,related="terminal_id.usage",readonly=True)
    employee_id         = fields.Many2one("hr.employee","employée" ,compute="_get_employee")
    sens    = fields.Selection([('in','In'),('out','Out')] , 'Sens',default=False,related="terminal_id.sens")


    @api.depends('terminal_sn')
    def _get_terminal(self):
        for o in self:
            o.terminal_id = self.env["zk.terminals"].search([('sn','=',o.terminal_sn)])

    @api.depends('emp_code')
    def _get_employee(self):
        for o in self:
            o.employee_id = self.env["hr.employee"].search([('barcode','=',o.emp_code)])
   
   
    def sync_transactions(self):
        self.env['zk.terminals'].search([]).sync_transaction()
        
        
        BASE_URL,_,_,AUTH = self.env["zk.connector"]._get_connection_params()
        API = f"/att/api/manuallogs/"
        
        for o in self:
            params= {}
            page = 1
            while True:
                params["page"] = page
                res = requests.get(f"{BASE_URL}{API}", auth=AUTH, params=params, timeout=60)
                if res.status_code != 200:
                    raise ValueError(f"Failed to fetch Transactions: {res.text}")
                data = res.json()
                tx_list = data.get("data", [])
                if not tx_list:
                    break

                for tx in tx_list:
                    val = {
                        "tid"               :tx.get("id"),                
                        "emp"               :tx.get("emp"),                
                        "emp_code"          :tx.get("emp_code"),           
                        "first_name"        :tx.get("first_name"),         
                        "last_name"         :tx.get("last_name"),          
                        "punch_time"        :tx.get("punch_time"),         
                        "terminal_sn"       :tx.get("terminal_sn"),        
                        "terminal_alias"    :tx.get("terminal_alias"),     
                        "upload_time"       :tx.get("upload_time"),        
                    }

                    if not self.env['zk.transaction'].search([('tid','=',tx.get('id'))]):
                        self.env['zk.transaction'].create(val)
                        
                            
                    

                if not data.get("next"):
                    break
                page += 1
   
class HrAttendanceManual(models.Model):
    _name = 'hr.attendance.manual'
    _description = 'Pointage manuel / corrections'

    employee_id = fields.Many2one('hr.employee', string='Employé')
    check_in = fields.Datetime(string='Heure d’entrée')
    check_out = fields.Datetime(string='Heure de sortie')
    day = fields.Date(string='Jour')
    type = fields.Selection([('manual','Manuel'),('we','WE'),('holiday','Férié')], string='Type', default='manual')
    note = fields.Char(string='Note')
