# -*- coding: utf-8 -*-
"""File d'envoi : traitement des opérations « Employé »."""
import logging

from odoo import _, api, fields, models

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 5


class ZkOutbox(models.Model):
    _inherit = 'itv.zk.outbox'

    operation = fields.Selection(selection_add=[('employee', "Employé")], ondelete={'employee': 'cascade'})

    @api.model
    def _enqueue_employee(self, employee, backend):
        """Ajoute (ou réutilise) une demande d'envoi pour cet employé."""
        pending = self.search([
            ('backend_id', '=', backend.id), ('operation', '=', 'employee'),
            ('res_model', '=', 'hr.employee'), ('res_id', '=', employee.id),
            ('state', 'in', ('pending', 'error')),
        ], limit=1)
        payload = {'barcode': employee.barcode, 'name': employee.name, 'pin': bool(employee.sudo().pin)}
        if pending:
            pending.write({'payload': payload, 'state': 'pending', 'last_error': False})
            return pending
        return self.create({
            'backend_id': backend.id, 'operation': 'employee', 'payload': payload,
            'res_model': 'hr.employee', 'res_id': employee.id, 'state': 'pending',
        })

    def _process_employee(self):
        """Envoie les demandes « Employé » ; chaque échec reste rejouable."""
        Employee = self.env['hr.employee']
        for entry in self:
            employee = Employee.browse(entry.res_id).exists()
            if not employee:
                entry.write({'state': 'error', 'last_error': _("Employé supprimé dans Odoo.")})
                continue
            try:
                with self.env.cr.savepoint():
                    biotime_id = entry.backend_id._push_employee(employee)
                    employee.write({
                        'itv_biotime_emp_id': biotime_id,
                        'itv_biotime_code': employee.barcode,
                        'itv_push_state': 'sent',
                        'itv_push_error': False,
                        'itv_pushed_at': fields.Datetime.now(),
                    })
                    entry.write({
                        'state': 'confirmed', 'biotime_ref': str(biotime_id),
                        'sent_at': fields.Datetime.now(), 'attempts': entry.attempts + 1, 'last_error': False,
                    })
            except Exception as error:
                message = str(error)[:500]
                logger.warning("Envoi BioTime de l'employé %s : %s", employee.display_name, message)
                entry.write({'state': 'error', 'attempts': entry.attempts + 1, 'last_error': message})
                employee.write({'itv_push_state': 'error', 'itv_push_error': message})

    @api.model
    def _cron_process_employees(self, limit=50):
        entries = self.search([
            ('operation', '=', 'employee'), ('state', '=', 'pending'), ('attempts', '<', MAX_ATTEMPTS),
        ], limit=limit)
        entries._process_employee()
        return len(entries)
