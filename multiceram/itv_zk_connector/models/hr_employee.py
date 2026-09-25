# -*- coding: utf-8 -*-
from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    itv_biotime_emp_id = fields.Integer("ID employé BioTime", groups='hr.group_hr_user', copy=False, index=True)
    itv_biotime_sync_hash = fields.Char("Empreinte de synchronisation BioTime", groups='hr.group_hr_user', copy=False)
    itv_to_complete = fields.Boolean(
        "Fiche à compléter", groups='hr.group_hr_user', copy=False,
        help="Employé créé par la synchronisation BioTime : poste, contrat et coordonnées restent à renseigner.")

    def _itv_biotime_changes(self, vals):
        """Libellés des champs que BioTime s'apprête à changer, pour la trace."""
        self.ensure_one()
        changes = []
        # fields_get rend le libellé traduit ; field.string reste en anglais.
        labels = self.fields_get(list(vals), ['string'])
        for name, value in vals.items():
            field = self._fields.get(name)
            if not field or name == 'itv_biotime_sync_hash':
                continue
            current = self[name]
            if isinstance(current, models.Model):
                current = current.id or False
            if current != value:
                label = labels.get(name, {}).get('string') or field.string
                changes.append("%s : %s → %s" % (label, current or '—', value or '—'))
        return changes
