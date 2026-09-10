# -*- coding: utf-8 -*-

# from odoo import models, fields, api


# class nabi_hr(models.Model):
#     _name = 'nabi_hr.nabi_hr'
#     _description = 'nabi_hr.nabi_hr'

#     name = fields.Char()
#     value = fields.Integer()
#     value2 = fields.Float(compute="_value_pc", store=True)
#     description = fields.Text()
#
#     @api.depends('value')
#     def _value_pc(self):
#         for record in self:
#             record.value2 = float(record.value) / 100

from odoo import models,fields, api, _
import requests,json,base64
from odoo.exceptions import UserError
from datetime import datetime, timedelta
import logging
_logger = logging.getLogger(__name__)

class HrLeave(models.Model):
    _inherit = 'hr.leave'

    def _check_validity(self):
        # Désactive la vérification de solde
        return True



class HrAttendanceManual(models.Model):
    _name = 'hr.attendance.manual'
    _description = 'Pointage manuel / corrections'

    employee_id = fields.Many2one('hr.employee', string='Employé')
    check_in = fields.Datetime(string='Heure d’entrée')
    check_out = fields.Datetime(string='Heure de sortie')
    day = fields.Date(string='Jour')
    type = fields.Selection([('manual','Manuel'),('we','WE'),('holiday','Férié')], string='Type', default='manual')
    note = fields.Char(string='Note')


class ZkBioTimeConnector(models.Model):
    _name = "zk.biotime.connector"
    _description = "ZK BioTime Connector"

    @api.model
    def _get_connection_params(self):
        ICP = self.env['ir.config_parameter'].sudo()
        server = ICP.get_param("zk.server")
        user = ICP.get_param("zk.user")
        password = ICP.get_param("zk.password")
        if not server or not user or not password:
            raise UserError(_("ZK BioTime connection parameters are not configured."))
        return server, user, password

    @api.model
    def _get_token(self):
        server, user, password = self._get_connection_params()
        url = f"{server}/api-token-auth/"
        headers = {
            "Content-Type": "application/json",
        }
        data = {
            "username": f"{user}",
            "password": f"{password}"
        }

        response = requests.post(url, data=json.dumps(data), headers=headers,timeout=30)
        print(response.text)

        ###
        
        if response.status_code != 200:
            raise UserError(_("Failed to login to BioTime: %s") % response.text)
        return response.json().get("token")


    @api.model
    def fetch_employees(self, next=None, page=None,page_size=None):
        server, user, password = self._get_connection_params()

        # Create the base64-encoded string
        credentials = f"{user}:{password}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()

        headers = {
                   "Authorization": f"Basic {encoded_credentials}"
                   }

        
        url = next or f"{server}/personnel/api/employees/?page={page or ''}&page_size={page_size or ''}"
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code != 200:
            raise UserError(_("Failed to fetch employees: %s") % resp.text)
        return resp.json()
        #.get("data", [])
    


    @api.model
    def sync_employees(self,page_size=10,page=None):
        employees   = self.fetch_employees(page_size=1)
        count       = employees.get("count", False)
        next_url = None

        
        for i in range(0,int(1+count/page_size)):
            employees  = self.fetch_employees(next = next_url,page_size=page_size)
            employees_data = employees.get("data", [])
            next_url        = employees.get("next", False)


            for emp in employees_data:
                matricule   = emp.get("emp_code")  # unique code in BioTime
                app_code    = emp.get("device_password")   # used as password
                name        = emp.get("first_name") or emp.get("full_name") or 'Unnamed'
                department  = emp.get("department") and  emp.get("department")['dept_name'] or "Undefined"

                # Find or create department
                dept = self.env["hr.department"].sudo().search([("name", "=", department)], limit=1)
                if not dept:
                    dept = self.env["hr.department"].sudo().create({"name": department})

                # Find employee
                employee = self.env["hr.employee"].sudo().search(['|',("identification_id", "=", matricule),("barcode", "=", matricule)], limit=1)
                
                if not name:
                    continue
                if not employee:
                    employee = self.env["hr.employee"].sudo().create({
                        "name": name,
                        "barcode": matricule,
                        "department_id": dept.id,
                    })
                else:
                    # Update department if changed
                    employee.department_id = dept.id
                    employee.pin = matricule

                # Ensure portal user exists
                user = self.env["res.users"].sudo().search([("login", "=", matricule)], limit=1)
                if not user:
                    user = self.env["res.users"].sudo().create({
                        "name": name,
                        "login": matricule,
                        "password": matricule,
                        "groups_id": [(6, 0, [self.env.ref("base.group_portal").id])],
                        "employee_id": employee.id,
                    })

                    employee.user_id = user.id
                else:
                    employee.user_id = user.id

            self.env.cr.commit()
    
    @api.model
    def get_punches(self, emp_code, day_from=None, day_to=None):
        """
        Fetch punches for an employee and classify by device type:
        - shift: main shift punches (6-14,14-22,22-6)
        - entrance: check-in/out / turnstile devices
        - restaurant: punches in restaurant device (6-14 shift only)
        """

        BASE_URL = self.env['ir.config_parameter'].sudo().get_param('zk.server')
        USER = self.env['ir.config_parameter'].sudo().get_param('zk.user')
        PASSWORD = self.env['ir.config_parameter'].sudo().get_param('zk.password')
        AUTH = (USER, PASSWORD)

        API = "/iclock/api/transactions/"

        params = {"emp_code": emp_code, "page_size": 50, "ordering": "punch_time"}

        if day_from:
            params["start_time"] = f"{day_from} 00:00:00"
        if day_to:
            params["end_time"] = f"{day_to} 23:59:59"

        all_punches = []
        page = 1
        while True:
            params["page"] = page
            res = requests.get(f"{BASE_URL}{API}", auth=AUTH, params=params, timeout=30)
            if res.status_code != 200:
                raise ValueError(f"Failed to fetch punches: {res.text}")
            data = res.json()
            tx_list = data.get("data", [])
            if not tx_list:
                break

            for tx in tx_list:
                terminal = tx.get("terminal_alias") or tx.get("terminal_sn")
                # classify device type
                if terminal.lower() in ["direction", "shift"]:
                    device_type = "shift"
                elif terminal.lower() in ["restaurant"]:
                    device_type = "restaurant"
                else:
                    device_type = "entrance"

                all_punches.append({
                    "id":tx["id"],
                    "punch_time": tx["punch_time"],
                    "terminal_sn": tx["terminal_sn"],
                    "terminal_alias": tx["terminal_alias"],
                    "device_type": device_type,
                    "emp_code": emp_code
                })

            if not data.get("next"):
                break
            page += 1

        # Sort by punch_time
        all_punches.sort(key=lambda x: datetime.strptime(x["punch_time"], "%Y-%m-%d %H:%M:%S"))
        _logger.critical("###### \n %s" ,all_punches ) 
        return all_punches