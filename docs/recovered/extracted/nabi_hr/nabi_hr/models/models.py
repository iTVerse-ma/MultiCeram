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
    def fetch_employees(self):
        server, user, password = self._get_connection_params()

        # Create the base64-encoded string
        credentials = f"{user}:{password}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()

        headers = {
                   "Authorization": f"Basic {encoded_credentials}"
                   }

        
        url = f"{server}/personnel/api/employees/"
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code != 200:
            raise UserError(_("Failed to fetch employees: %s") % resp.text)
        return resp.json().get("data", [])
    


    @api.model
    def sync_employees(self):
        employees = self.fetch_employees()
        for emp in employees:
            matricule = emp.get("emp_code")  # unique code in BioTime
            app_code = emp.get("device_password")   # used as password
            name = emp.get("first_name") or emp.get("first_name")
            department = emp.get("department") and  emp.get("department")['dept_name'] or "Undefined"

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
