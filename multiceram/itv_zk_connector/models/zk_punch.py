# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from ..services.timeutils import local_to_utc, parse_local

PUNCH_SOURCES = [
    ('device', "Terminal"),
    ('manual_log', "Pointage manuel BioTime"),
    ('odoo_manual', "Saisie Odoo"),
    ('migrated_manual', "Manuel (migré)"),
]


class ItvZkPunch(models.Model):
    _name = 'itv.zk.punch'
    _inherit = ['itv.audit.mixin']
    _description = "Transaction BioTime"
    _order = 'punch_time desc, id desc'
    _rec_name = 'punch_local'

    backend_id = fields.Many2one('itv.zk.backend', string="Connexion", required=True, ondelete='restrict')
    company_id = fields.Many2one(related='backend_id.company_id', store=True, index=True)
    source = fields.Selection(PUNCH_SOURCES, string="Source", required=True, default='device')
    biotime_id = fields.Integer("ID transaction BioTime", copy=False)
    biotime_manuallog_id = fields.Integer("ID pointage manuel BioTime", copy=False)
    emp_code = fields.Char("Matricule", index=True)
    employee_id = fields.Many2one('hr.employee', string="Employé", ondelete='set null')
    punch_local = fields.Char("Heure locale", required=True, help="Heure telle qu'envoyée par BioTime, sans conversion.")
    punch_time = fields.Datetime("Heure", required=True)
    punch_date = fields.Date("Date", required=True)
    terminal_id = fields.Many2one('itv.zk.terminal', string="Terminal", ondelete='restrict')
    terminal_sn = fields.Char("N° de série du terminal")
    terminal_alias = fields.Char("Nom du terminal (BioTime)")
    area_alias = fields.Char("Zone")
    usage = fields.Selection(related='terminal_id.usage', store=True, string="Usage")
    direction = fields.Selection(related='terminal_id.direction', store=True, string="Sens")
    punch_state = fields.Char("État BioTime")
    verify_type = fields.Char("Mode de vérification")
    work_code = fields.Char("Code travail")
    upload_time = fields.Datetime("Reçu par BioTime", index=True)
    upload_delay_min = fields.Integer("Retard de réception (min)", compute='_compute_upload_delay', store=True)
    duplicate = fields.Boolean("Doublon", tracking=True)
    duplicate_origin = fields.Selection(
        [('migrated', "Migré"), ('rule_5min', "Règle 5 min"), ('rule_30min', "Règle 30 min"), ('manual', "Manuel")],
        string="Origine du doublon")
    to_delete = fields.Boolean("Écarté", tracking=True, help="Suppression logique : le pointage reste en base mais sort du calcul historique.")
    date_override = fields.Date("Date appliquée", tracking=True, help="Rattache le pointage à un autre jour dans le calcul historique.")

    _device_uniq = models.UniqueIndex("(backend_id, biotime_id) WHERE source = 'device'", "Cette transaction BioTime est déjà importée.")
    _manuallog_uniq = models.UniqueIndex("(backend_id, biotime_manuallog_id) WHERE biotime_manuallog_id <> 0", "Ce pointage manuel BioTime est déjà importé.")
    _employee_date_idx = models.Index('(employee_id, punch_date)')
    _terminal_time_idx = models.Index('(terminal_id, punch_time)')
    _date_usage_idx = models.Index('(punch_date, usage)')

    @api.depends('upload_time', 'punch_time')
    def _compute_upload_delay(self):
        for punch in self:
            if punch.upload_time and punch.punch_time:
                punch.upload_delay_min = int((punch.upload_time - punch.punch_time).total_seconds() // 60)
            else:
                punch.upload_delay_min = 0

    @api.constrains('source', 'biotime_id')
    def _check_device_id(self):
        for punch in self:
            if punch.source == 'device' and not punch.biotime_id:
                raise ValidationError(_("Un pointage de terminal doit porter l'identifiant de transaction BioTime."))

    # -- Import ---------------------------------------------------------------------------

    @api.model
    def _import_biotime_transactions(self, backend, records):
        """Crée les pointages absents d'une page de transactions BioTime ; rend les pointages créés."""
        candidates = {int(rec['id']): rec for rec in records if rec.get('id') is not None and rec.get('punch_time')}
        if not candidates:
            return self.browse()
        self.env.cr.execute(
            "SELECT biotime_id FROM itv_zk_punch WHERE backend_id = %s AND source = 'device' AND biotime_id = ANY(%s)",
            [backend.id, list(candidates)],
        )
        for (known_id,) in self.env.cr.fetchall():
            candidates.pop(known_id, None)
        if not candidates:
            return self.browse()
        employee_ids = self._employee_ids_by_code(rec.get('emp_code') for rec in candidates.values())
        terminals = self.env['itv.zk.terminal']._get_or_create_by_sn(
            backend, {(rec.get('terminal_sn') or '').strip(): rec.get('terminal_alias') for rec in candidates.values()})
        punches = self.create([
            self._prepare_device_vals(backend, biotime_id, rec, employee_ids, terminals)
            for biotime_id, rec in candidates.items()
        ])
        punches._on_punches_imported()
        return punches

    @api.model
    def _employee_ids_by_code(self, codes):
        codes = {code.strip() for code in codes if code and code.strip()}
        if not codes:
            return {}
        employees = self.env['hr.employee'].sudo().with_context(active_test=False).search_read(
            [('barcode', 'in', list(codes))], ['barcode'])
        return {employee['barcode']: employee['id'] for employee in employees}

    @api.model
    def _prepare_device_vals(self, backend, biotime_id, record, employee_ids, terminals):
        serial = (record.get('terminal_sn') or '').strip()
        terminal = terminals.get(serial) or self.env['itv.zk.terminal']
        punch_local = record['punch_time'].strip()
        code = (record.get('emp_code') or '').strip()
        upload = record.get('upload_time')
        return {
            'backend_id': backend.id,
            'source': 'device',
            'biotime_id': biotime_id,
            'emp_code': code or False,
            'employee_id': employee_ids.get(code, False),
            'punch_local': punch_local,
            'punch_time': local_to_utc(punch_local, terminal.timezone_override or backend.timezone),
            'punch_date': parse_local(punch_local).date(),
            'terminal_id': terminal.id,
            'terminal_sn': serial or False,
            'terminal_alias': record.get('terminal_alias') or False,
            'area_alias': record.get('area_alias') or False,
            'punch_state': self._as_text(record.get('punch_state')),
            'verify_type': self._as_text(record.get('verify_type')),
            'work_code': self._as_text(record.get('work_code')),
            # Heure du serveur BioTime : toujours dans le fuseau de la connexion.
            'upload_time': local_to_utc(upload, backend.timezone) if upload else False,
        }

    @staticmethod
    def _as_text(value):
        return False if value in (None, '') else str(value)

    def _on_punches_imported(self):
        """Point d'extension : itv_zk_attendance y marque les journées à recalculer."""
