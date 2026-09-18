# -*- coding: utf-8 -*-
"""Écriture des employés vers BioTime, en réutilisant le client HTTP du connecteur."""
from odoo import _, fields, models
from odoo.exceptions import UserError

EMPLOYEES_PATH = 'personnel/api/employees/'
DEPARTMENTS_PATH = 'personnel/api/departments/'
AREAS_PATH = 'personnel/api/areas/'
# BioTime n'expose pas de mise en sommeil : un employé archivé est déplacé dans une zone sans
# pointeuse, ce qui fait retirer son profil des terminaux tout en gardant son historique.
ARCHIVE_AREA_CODE = 'ARCHIVE'
ARCHIVE_AREA_NAME = "Archivés (Odoo)"


class ZkBackend(models.Model):
    _inherit = 'itv.zk.backend'

    push_department_code = fields.Char(
        "Département BioTime par défaut", default='1',
        help="Code du département BioTime utilisé quand l'employé Odoo n'est rattaché à aucun département connu.\n"
             "Le code se lit dans BioTime : Personnel → Département, colonne « Numéro de département ».")
    push_area_code = fields.Char(
        "Zone BioTime par défaut", default='1',
        help="Code de la zone BioTime dans laquelle placer les employés envoyés. "
             "Les pointeuses de cette zone reçoivent automatiquement ces employés.\n"
             "Le code se lit dans BioTime : Personnel → Zone, colonne « Numéro de zone ». "
             "Un employé archivé dans Odoo est déplacé vers la zone « Archivés (Odoo) », sans pointeuse : "
             "son profil est retiré des terminaux, son historique est conservé.")

    def _archive_area_id(self, client):
        """Zone d'archivage, créée à la demande."""
        self.ensure_one()
        area_id = self._lookup_reference(client, AREAS_PATH, 'area_code', ARCHIVE_AREA_CODE)
        records = list(client.iter_records(AREAS_PATH, params={self.page_size_param: 100}))
        if not any(str(record.get('area_code')) == ARCHIVE_AREA_CODE for record in records):
            created = client.request('POST', AREAS_PATH, json={
                'area_code': ARCHIVE_AREA_CODE, 'area_name': ARCHIVE_AREA_NAME})
            area_id = (created or {}).get('id') or area_id
        return area_id

    def _push_reference_ids(self, client, employee):
        """Identifiants BioTime (département, zones) à utiliser pour cet employé."""
        self.ensure_one()
        department_id = employee.department_id.itv_biotime_dept_id if 'itv_biotime_dept_id' in employee.department_id._fields else 0
        if not department_id:
            department_id = self._lookup_reference(client, DEPARTMENTS_PATH, 'dept_code', self.push_department_code)
        if not employee.active:
            area_id = self._archive_area_id(client)
        else:
            area_id = self._lookup_reference(client, AREAS_PATH, 'area_code', self.push_area_code)
        if not department_id or not area_id:
            raise UserError(_("Département ou zone introuvable dans BioTime (codes %s / %s).")
                            % (self.push_department_code, self.push_area_code))
        return department_id, [area_id]

    def _lookup_reference(self, client, path, code_field, code):
        """Cherche un enregistrement de référence par son code ; à défaut, prend le premier."""
        records = list(client.iter_records(path, params={self.page_size_param: 100}))
        for record in records:
            if code and str(record.get(code_field) or '') == str(code):
                return record.get('id')
        return records[0].get('id') if records else 0

    def _push_employee_payload(self, employee, department_id, area_ids):
        first_name, _sep, last_name = (employee.name or '').partition(' ')
        payload = {
            'emp_code': employee.barcode,
            'first_name': first_name or employee.barcode,
            'last_name': last_name or '',
            'department': department_id,
            'area': area_ids,
        }
        if employee.itv_biotime_pin:
            payload['device_password'] = employee.itv_biotime_pin
        return payload

    def _push_employee(self, employee):
        """Crée ou met à jour l'employé dans BioTime ; renvoie son identifiant BioTime."""
        self.ensure_one()
        if not employee.barcode:
            raise UserError(_("L'employé « %s » n'a pas de matricule : impossible de l'envoyer à BioTime.")
                            % employee.display_name)
        client = self._get_client()
        department_id, area_ids = self._push_reference_ids(client, employee)
        payload = self._push_employee_payload(employee, department_id, area_ids)
        if employee.itv_biotime_emp_id:
            response = client.request('PATCH', '%s%s/' % (EMPLOYEES_PATH, employee.itv_biotime_emp_id), json=payload)
        else:
            response = client.request('POST', EMPLOYEES_PATH, json=payload)
        biotime_id = (response or {}).get('id') or employee.itv_biotime_emp_id
        if not biotime_id:
            raise UserError(_("BioTime n'a pas renvoyé d'identifiant pour « %s ».") % employee.display_name)
        return biotime_id
