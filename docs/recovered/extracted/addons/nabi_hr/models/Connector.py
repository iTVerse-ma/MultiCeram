# -*- coding: utf-8 -*-

from odoo import models,fields, api, _
import requests,json,base64
from odoo.exceptions import UserError
from datetime import datetime, timedelta
import logging
_logger = logging.getLogger(__name__)




class ZkBioTimeConnector(models.Model):
    _name = "zk.connector"
    _description = "ZK BioTime Connector"

    @api.model
    def _get_connection_params(self):
        ICP         = self.env['ir.config_parameter'].sudo()
        server      = ICP.get_param("zk.server")
        user        = ICP.get_param("zk.user")
        password    = ICP.get_param("zk.password")
        auth         = (user, password)

        if not server or not user or not password:
            raise UserError(_("ZK BioTime connection parameters are not configured."))
        return server, user, password,auth

    @api.model
    def _get_token(self):
        server, user, password, auth = self._get_connection_params()
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
        server, user, password,auth = self._get_connection_params()

        # Create the base64-encoded string
        credentials = f"{user}:{password}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()

        headers = {
                   "Authorization": f"Basic {encoded_credentials}"
                   }

        
        url = next or f"{server}/personnel/api/employees/?page={page or ''}&page_size={page_size or ''}"
        resp = requests.get(url, headers=headers, timeout=60)
        if resp.status_code != 200:
            raise UserError(_("Failed to fetch employees: %s") % resp.text)
        return resp.json()
        #.get("data", [])
    


    @api.model
    def sync_employees(self,page_size=10,page=None):
        employees   = self.fetch_employees(page_size=1)
        count       = employees.get("count", False)
        next_url = None

        
        for i in range(page and page - 1 or 0,int(1+count/page_size)):
            _logger.critical(f" Sync Employee page {i}/{page_size}")
            employees  = self.fetch_employees(next = next_url,page_size=page_size,page=not next_url and i or None)
            employees_data = employees.get("data", [])
            next_url        = employees.get("next", False)
            _logger.critical(f"####. {len(employees_data)}")


            for emp in employees_data:
                matricule   = emp.get("emp_code")  # unique code in BioTime
                app_code    = emp.get("device_password")   # used as password
                name        = f'{emp.get("first_name")}  {emp.get("full_name")}'
                department  = emp.get("department") and  emp.get("department")['dept_name'] or "Undefined"
                _logger.critical(f"===> employee {name}")

                # Find or create department
                dept = self.env["hr.department"].sudo().search([("name", "=", department)], limit=1)
                if not dept:
                    dept = self.env["hr.department"].sudo().create({"name": department})

                # Find employee
                employee = self.env["hr.employee"].sudo().search(['|',("identification_id", "=", matricule),("barcode", "=", matricule)], limit=1)
                
                if not name:
                    _logger.critical(f" Unnamed Employee  {name} --> code : {matricule} ")
                    continue
                if not employee:
                    employee = self.env["hr.employee"].sudo().create({
                        "name": name,
                        "barcode": matricule,
                        "department_id": dept.id,
                    })
                    self.env.cr.commit()
                    _logger.critical(f" Create Employee {name} --> code : {matricule}")
                else:
                    # Update department if changed
                    employee.department_id = dept.id
                    employee.pin = matricule
                    employee.name = name
                    employee.zk_id = emp.get('id')
                    _logger.critical(f"  Employee existes {name} --> code : {matricule} ")
                    self.env.cr.commit()

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
                    self.env.cr.commit()
                else:
                    employee.user_id = user.id
                    self.env.cr.commit()

            self.env.cr.commit()
    
    @api.model
    def get_punches(self, emp_code=None, day_from=None, day_to=None,page_size=50000):
        """
        Fetch punches for an employee and classify by device type:
        - shift: main shift punches (6-14,14-22,22-6)
        - entrance: check-in/out / turnstile devices
        - restaurant: punches in restaurant device (6-14 shift only)
        """

        BASE_URL        = self.env['ir.config_parameter'].sudo().get_param('zk.server')
        USER            = self.env['ir.config_parameter'].sudo().get_param('zk.user')
        PASSWORD        = self.env['ir.config_parameter'].sudo().get_param('zk.password')
        AUTH            = (USER, PASSWORD)

        API = "/iclock/api/transactions/"

        params = {"emp_code": emp_code, "page_size": page_size, "ordering": "punch_time"}
        # return params
        if day_from:
            params["start_time"] = f"{day_from} 00:00:00"
        if day_to:
            params["end_time"] = f"{day_to} 23:59:59"

        all_punches = []
        page = 1
        while True:
            params["page"] = page
            res = requests.get(f"{BASE_URL}{API}", auth=AUTH, params=params)
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
                    "emp_code": tx['emp_code'],
                    "emp_id": tx['emp']
                })

            if not data.get("next"):
                break
            page += 1
            _logger.critical(f"######### {tx}")

        # Sort by punch_time
        all_punches.sort(key=lambda x: datetime.strptime(x["punch_time"], "%Y-%m-%d %H:%M:%S"))
        _logger.critical(f"###### emp:{emp_code}, day_from={day_from}, day_to={day_to} -> {all_punches}" , ) 
        return all_punches
