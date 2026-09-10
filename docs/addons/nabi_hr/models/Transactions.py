# -*- coding: utf-8 -*-

from odoo import models,fields, api, _
import requests,json,base64
from odoo.exceptions import UserError
from datetime import datetime, timedelta
import logging
_logger = logging.getLogger(__name__)


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
    
    last_tid = fields.Integer(
        string="Dernier ID de transaction",
        compute="_compute_last_tid",
        store=False,
    )
    def _compute_last_tid(self):
        """Compute last transaction ID per terminal."""
        Tx = self.env['zk.transaction']
        for rec in self:
            last_tx = Tx.search(
                [('terminal_sn', '=', rec.sn)],
               
               
            ).sorted(lambda x:x.tid.zfill(10),reverse=True)[:1]
            rec.last_tid = last_tx.tid if last_tx else 0
    # ------------------------------------------------------------------
    @api.model
    def sync_manual_transaction(self,start_time=None):
        """Synchronise les transactions depuis le dernier ID connu pour chaque terminal."""
        BASE_URL, _, _, AUTH = self.env["zk.connector"]._get_connection_params()
        API = "iclock/api/transactions/"
        Tx = self.env["zk.transaction"]

    
        self.env.cr.commit()
        last_id = self.env['zk.transaction'].search([('terminal_sn','=',False)]).sorted(lambda x:x.tid.zfill(10),reverse=True)[:1].tid
        
        
        params = {
            "terminal_sn": None,
            "last_id": last_id or None,
            "page": 1,
            "page_size": 100,
            "ordering": "id",
        }

        if start_time:
            params['start_time'] = start_time

        max_tid = last_id and int(last_id) or None
        batch = []
        print(f"🔄 Sync #MANUALS# starting from ID {last_id}")

        while True:
            try:
                res = requests.get(f"{BASE_URL}{API}", auth=AUTH, params=params, timeout=120)
                res.raise_for_status()
            except Exception as e:
                raise ValueError(f"Erreur API pour #MANUALS#: {e}")

            data = res.json()
            tx_list = data.get("data", [])
            if not tx_list:
                break

            for tx in tx_list:
                tid = tx.get("id")
                if not tid:
                    continue

                if Tx.search_count([("tid", "=", tid)]) > 0:
                    continue

                batch.append({
                    "tid": tid,
                    "emp": tx.get("emp"),
                    "emp_code": tx.get("emp_code"),
                    "first_name": tx.get("first_name"),
                    "last_name": tx.get("last_name"),
                    "punch_time": tx.get("punch_time"),
                    "terminal_sn": tx.get("terminal_sn"),
                    "terminal_alias": tx.get("terminal_alias"),
                    "upload_time": tx.get("upload_time"),
                })
                max_tid = max(max_tid, int(tid))

            if batch:
                Tx.create(batch)
                self.env.cr.commit()
                batch = []

            if not data.get("next"):
                break
            params["page"] += 1

        # terminal.last_sync = datetime.now()
        self.env.cr.commit()
        print(f"✅ #Manuals# synced (up to ID {max_tid})")

    # ------------------------------------------------------------------
    def sync_transaction(self):
        """Synchronise les transactions depuis le dernier ID connu pour chaque terminal."""
        BASE_URL, _, _, AUTH = self.env["zk.connector"]._get_connection_params()
        API = "iclock/api/transactions/"
        Tx = self.env["zk.transaction"]

        for terminal in self:
            self.env.cr.commit()
            last_id = terminal.last_tid or 0
            params = {
                "terminal_sn": terminal.sn,
                "last_id": last_id,
                "page": 1,
                "page_size": 100,
                "ordering": "id",
            }

            max_tid = last_id
            batch = []
            print(f"🔄 Sync {terminal.sn} starting from ID {last_id}")

            while True:
                try:
                    res = requests.get(f"{BASE_URL}{API}", auth=AUTH, params=params, timeout=120)
                    res.raise_for_status()
                except Exception as e:
                    raise ValueError(f"Erreur API pour {terminal.sn}: {e}")

                data = res.json()
                tx_list = data.get("data", [])
                if not tx_list:
                    break

                for tx in tx_list:
                    tid = tx.get("id")
                    if not tid:
                        continue

                    if Tx.search_count([("tid", "=", tid)]) > 0:
                        continue

                    batch.append({
                        "tid": tid,
                        "emp": tx.get("emp"),
                        "emp_code": tx.get("emp_code"),
                        "first_name": tx.get("first_name"),
                        "last_name": tx.get("last_name"),
                        "punch_time": tx.get("punch_time"),
                        "terminal_sn": tx.get("terminal_sn"),
                        "terminal_alias": tx.get("terminal_alias"),
                        "upload_time": tx.get("upload_time"),
                    })
                    max_tid = max(max_tid, tid)

                if batch:
                    Tx.create(batch)
                    self.env.cr.commit()
                    batch = []

                if not data.get("next"):
                    break
                params["page"] += 1

            terminal.last_sync = datetime.now()
            self.env.cr.commit()
            print(f"✅ {terminal.sn} synced (up to ID {max_tid})")

        self._mark_recent_duplicates()
        #self.sync_manual_transaction("2025-11-01")

    # ------------------------------------------------------------------
    def _mark_recent_duplicates(self,cutoff=True):
        """Mark duplicates within 30 min for recent transactions."""
        
        Tx = self.env["zk.transaction"]
        domain = []
        if cutoff:
            cutoff = datetime.now() - timedelta(days=2)
            domain=  [("punch_time", ">=", cutoff.strftime("%Y-%m-%d %H:%M:%S"))]

        recent_txs = Tx.search(
           domain,
            order="emp_code, punch_time"
        )

        last_seen = {}
        for tx in recent_txs:
            emp = tx.emp_code
            pt = fields.Datetime.from_string(tx.punch_time)
            if emp in last_seen:
                last_time = last_seen[emp]
                tx.duplicate = (pt - last_time) < timedelta(minutes=30)
            else:
                tx.duplicate = False
            last_seen[emp] = pt


    def sync_terminals(self):
        pass
        BASE_URL,_,_,AUTH = self.env["zk.connector"]._get_connection_params()

        API = f"iclock/api/terminals/"
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

    def __sync_transaction(self):
        BASE_URL,_,_,AUTH = self.env["zk.connector"]._get_connection_params()
        API = f"iclock/api/transactions/"
        
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


    tid                 = fields.Char("Transaction id")
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
    employee_id         = fields.Many2one("hr.employee","employée" ,compute="_get_employee",search="_search_employee")
    sens                = fields.Selection([('in','In'),('out','Out')] , 'Sens',default=False,related="terminal_id.sens")
    duplicate           = fields.Boolean("Dupliqué",default=False)
    to_delete           = fields.Boolean("To delete", default=False)
    # applied_day         = fields.Date("Applied date")
    # overnight           = fields.Boolean("Overnight")
    # schedule_id         = fields.Many2one("zk.schedule")


    



    @api.depends('terminal_sn')
    def _get_terminal(self):
        for o in self:
            o.terminal_id = self.env["zk.terminals"].search([('sn','=',o.terminal_sn)])

    @api.depends('emp_code')
    def _get_employee(self):
        for o in self:
            o.employee_id = self.env["hr.employee"].search([('active','in',(True,False)),('barcode','=',o.emp_code)])
   
    
    def _search_employee(self, operator, value):
        # operator: '=', 'ilike', etc.
        # value: the value used in the domain
        # Return a domain to apply
        
       
        return [('emp', operator, value)]
    
    
    def sync_transactions(self):
        self.env['zk.terminals'].search([]).sync_transaction()
        
        
        BASE_URL,_,_,AUTH = self.env["zk.connector"]._get_connection_params()
        API = f"att/api/manuallogs/"
        
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

class HrHolidays(models.Model):
    _inherit ="resource.calendar.leaves"


   
    def sync_holidays(self):
        """Synchronise les transactions depuis le dernier ID connu pour chaque terminal."""
        BASE_URL, _, _, AUTH = self.env["zk.connector"]._get_connection_params()
        API = "att/api/holidays/"
        params = {"page_size":10000}

        try:
            res = requests.get(f"{BASE_URL}{API}", auth=AUTH, params=params, timeout=120)
            res.raise_for_status()
        except Exception as e:
            raise ValueError(f"Erreur API Holidays : {e}")

        data = res.json()
        tx_list = data.get("data", [])
        if not tx_list:
            pass

        for tx in tx_list:
            tid = tx.get("id")
            existing = self.search([('resource_id', '=', False),('x_zkid','=',tid)])
            if existing:
                existing.name = tx.get("alias")
                existing.date_from = tx.get("start_date")
                existing.date_to = existing.date_from + timedelta(days= tx.get("duration_day") or 1,seconds=-1)
            else:
                existing.create({
                    'name': tx.get("alias"),
                    'date_from': tx.get("start_date"),
                    'date_to': fields.Datetime.from_string(tx.get("start_date")) + timedelta(days= tx.get("duration_day") or 1,seconds=-1),
                    'x_zkid': tx.get("id"),
                                 })
        
        for o in self.search([('resource_id', '=', False),('x_zkid','=',False)]):
            params = {
                    "alias": o.name,
                    "start_date": o.date_from.strftime("%Y-%m-%d"),
                    "end_date": o.date_to.strftime("%Y-%m-%d")
                   
                }
            try:
                res = requests.post(f"{BASE_URL}{API}", auth=AUTH, json=params, timeout=120)
                res.raise_for_status()
                data = res.json()
                tid = data.get("id", [])
                o.x_zkid = tid


            except Exception as e:
                raise ValueError(f"Erreur API Holidays : {e}")
            
