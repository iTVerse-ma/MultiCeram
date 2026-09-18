# -*- coding: utf-8 -*-
"""Chargement des données MultiCeram dans la base du module nabi_hr porté sur Odoo 19 (multiceram_nabi).

Périmètre (décision du 15/09/2026) :
- données de référence complètes : départements, employés et leurs réglages (champs x_*),
  terminaux (avec la référence nabi.uhf), paramètres BioTime sans mot de passe ni jeton ;
- pointages de septembre et octobre 2025 seulement, et les congés qui touchent ces deux mois.

Source : schéma `legacy` (copie des tables de mc2). À lancer sur une base neuve où nabi_hr 19.0
est installé ; rejouable (correspondances dans legacy.itv_map).

    docker compose exec -T odoo odoo shell -c /etc/odoo/odoo.conf -d multiceram_nabi \\
      --db_host db --db_user odoo --db_password <PG_PASSWORD> < tools/migration_nabi/30_load_nabi19.py
"""
import time

TZ = 'Africa/Casablanca'
PERIOD_START, PERIOD_END = '2025-09-01', '2025-11-01'   # fin exclue
EMPLOYEE_FIELDS = (
    'job_title', 'work_email', 'work_phone', 'mobile_phone', 'private_email', 'private_phone',
    'birthday', 'ssnid', 'employee_type', 'place_of_birth', 'marital',
    'x_acc_pin', 'x_acc_pin2', 'x_day_hour', 'x_heure_supp', 'x_horaire', 'x_ignore_uhf', 'x_pause', 'x_workedday_week',
)
LEAVE_FIELDS = (
    'request_date_from', 'request_date_to', 'request_date_from_period', 'request_unit_half',
    'request_unit_hours', 'request_hour_from', 'request_hour_to', 'private_name', 'notes',
)


def log(message, *args):
    print("nabi19: " + (message % args if args else message), flush=True)


def text(value):
    if isinstance(value, dict):
        return value.get('fr_FR') or value.get('en_US') or next(iter(value.values()), '')
    return value or ''


class Loader:

    def __init__(self, environment):
        self.env = environment(context=dict(environment.context, active_test=False, tracking_disable=True,
                                            mail_create_nolog=True, mail_create_nosubscribe=True, mail_notrack=True))
        self.cr = self.env.cr
        self.company = self.env.company
        self.errors = []
        self.cr.execute("""CREATE TABLE IF NOT EXISTS legacy.itv_map (
            model varchar NOT NULL, legacy_id integer NOT NULL, new_id integer NOT NULL, PRIMARY KEY (model, legacy_id))""")

    def mapped(self, model):
        self.cr.execute("SELECT legacy_id, new_id FROM legacy.itv_map WHERE model = %s", [model])
        return dict(self.cr.fetchall())

    def remember(self, model, legacy_id, new_id):
        self.cr.execute("""INSERT INTO legacy.itv_map (model, legacy_id, new_id) VALUES (%s, %s, %s)
                           ON CONFLICT (model, legacy_id) DO UPDATE SET new_id = EXCLUDED.new_id""", [model, legacy_id, new_id])

    def attempt(self, label, function):
        try:
            with self.cr.savepoint():
                return function()
        except Exception as exc:  # consigné dans le rapport
            self.errors.append("%s : %s" % (label, exc))
            return None

    def departments(self):
        Department = self.env['hr.department']
        done = self.mapped('hr.department')
        self.cr.execute("SELECT id, name, parent_id, active FROM legacy.hr_department ORDER BY parent_path NULLS FIRST, id")
        rows = self.cr.dictfetchall()
        for row in rows:
            if row['id'] in done:
                continue
            department = self.attempt("département %s" % row['id'], lambda row=row: Department.create({
                'name': text(row['name']) or "Département %s" % row['id'], 'active': bool(row['active']), 'company_id': self.company.id}))
            if department:
                done[row['id']] = department.id
                self.remember('hr.department', row['id'], department.id)
        for row in rows:
            if row['parent_id'] in done and row['id'] in done:
                Department.browse(done[row['id']]).parent_id = done[row['parent_id']]
        log("départements : %s", len(done))

    def employees(self):
        Employee = self.env['hr.employee']
        departments = self.mapped('hr.department')
        done = self.mapped('hr.employee')
        self.cr.execute("SELECT e.*, r.tz AS resource_tz FROM legacy.hr_employee e LEFT JOIN legacy.resource_resource r ON r.id = e.resource_id ORDER BY e.id")
        rows = self.cr.dictfetchall()
        for row in rows:
            if row['id'] in done:
                continue
            vals = {name: row[name] for name in EMPLOYEE_FIELDS if row.get(name) not in (None, '', False)}
            vals.update(
                name=text(row['name']) or row['barcode'] or "Employé %s" % row['id'],
                barcode=(row['barcode'] or '').strip() or False,
                pin=(row['pin'] or '').strip() or False,
                zk_id=row['zk_id'] or False,
                active=bool(row['active']),
                company_id=self.company.id,
                department_id=departments.get(row['department_id'], False),
                tz=row['resource_tz'] or TZ,
            )
            if row.get('gender'):
                vals['sex'] = row['gender']
            if row.get('identification_id'):
                vals['identification_id'] = row['identification_id']
            vals = {key: value for key, value in vals.items() if key in Employee._fields}
            employee = self.attempt("employé %s" % row['id'], lambda vals=vals: Employee.create(vals))
            if employee:
                done[row['id']] = employee.id
                self.remember('hr.employee', row['id'], employee.id)
        for row in rows:
            vals = {}
            if row['parent_id'] in done:
                vals['parent_id'] = done[row['parent_id']]
            if row['coach_id'] in done:
                vals['coach_id'] = done[row['coach_id']]
            if vals and row['id'] in done:
                self.attempt("hiérarchie %s" % row['id'], lambda row=row, vals=vals: Employee.browse(done[row['id']]).write(vals))
        log("employés : %s", len(done))

    def terminals(self):
        Terminal = self.env['zk.terminals']
        done = self.mapped('zk.terminals')
        self.cr.execute("SELECT id, tid, sn, alias, usage, sens, last_activity, last_sync FROM legacy.zk_terminals ORDER BY id")
        for row in self.cr.dictfetchall():
            if row['id'] in done:
                continue
            terminal = Terminal.create({name: row[name] for name in ('tid', 'sn', 'alias', 'usage', 'sens', 'last_activity', 'last_sync') if row[name] is not None})
            done[row['id']] = terminal.id
            self.remember('zk.terminals', row['id'], terminal.id)
        # Référence créée à la main dans mc2 et utilisée par le code : request.env.ref('nabi.uhf').
        self.cr.execute("SELECT res_id FROM legacy.ir_model_data WHERE module = 'nabi' AND name = 'uhf'")
        row = self.cr.fetchone()
        if row and row[0] in done and not self.env.ref('nabi.uhf', raise_if_not_found=False):
            self.env['ir.model.data'].create({'module': 'nabi', 'name': 'uhf', 'model': 'zk.terminals', 'res_id': done[row[0]], 'noupdate': True})
        log("terminaux : %s (nabi.uhf -> %s)", len(done), self.env.ref('nabi.uhf', raise_if_not_found=False))

    def transactions(self):
        self.cr.execute("SELECT count(*) FROM zk_transaction")
        if self.cr.fetchone()[0]:
            log("pointages : déjà chargés, étape ignorée")
            return
        started = time.monotonic()
        self.cr.execute("""
            INSERT INTO zk_transaction (terminal_id, tid, emp, emp_code, first_name, last_name, terminal_sn, terminal_alias,
                                        upload_time, punch_time, duplicate, to_delete, x_date_appliquee,
                                        create_uid, write_uid, create_date, write_date)
            SELECT m.new_id, x.tid, x.emp, x.emp_code, x.first_name, x.last_name, x.terminal_sn, x.terminal_alias,
                   x.upload_time, x.punch_time, x.duplicate, x.to_delete, x.x_date_appliquee,
                   %(uid)s, %(uid)s, now() AT TIME ZONE 'UTC', now() AT TIME ZONE 'UTC'
              FROM legacy.zk_transaction x
              LEFT JOIN legacy.itv_map m ON m.model = 'zk.terminals' AND m.legacy_id = x.terminal_id
             WHERE x.punch_time >= %(start)s AND x.punch_time < %(end)s
             ORDER BY x.id
        """, {'uid': self.env.uid, 'start': PERIOD_START, 'end': PERIOD_END})
        log("pointages %s → %s : %s insérés en %.1f s", PERIOD_START, PERIOD_END, self.cr.rowcount, time.monotonic() - started)

    def leaves(self):
        LeaveType = self.env['hr.leave.type']
        types = self.mapped('hr.leave.type')
        employees = self.mapped('hr.employee')
        self.cr.execute("""SELECT t.*, d.name AS xmlid FROM legacy.hr_leave_type t
                           LEFT JOIN legacy.ir_model_data d ON d.model = 'hr.leave.type' AND d.res_id = t.id AND d.module = 'hr_holidays' ORDER BY t.id""")
        for row in self.cr.dictfetchall():
            if row['id'] in types:
                continue
            target = self.env.ref('hr_holidays.%s' % row['xmlid'], raise_if_not_found=False) if row['xmlid'] else None
            if not target:
                vals = {'name': text(row['name']), 'active': bool(row['active']), 'company_id': self.company.id}
                for name in ('leave_validation_type', 'request_unit', 'time_type', 'unpaid'):
                    field = LeaveType._fields.get(name)
                    if field is not None and row.get(name) is not None:
                        vals[name] = row[name]
                if 'requires_allocation' in LeaveType._fields and row.get('requires_allocation') is not None:
                    vals['requires_allocation'] = row['requires_allocation'] in (True, 'yes')
                target = self.attempt("type de congé %s" % row['id'], lambda vals=vals: LeaveType.create(vals))
            if target:
                types[row['id']] = target.id
                self.remember('hr.leave.type', row['id'], target.id)
        # nabi_hr désactive le contrôle de solde (_check_validity) : les congés se reprennent sans attribution.
        Leave = self.env['hr.leave'].with_context(leave_skip_state_check=True, leave_skip_date_check=True)
        done = self.mapped('hr.leave')
        self.cr.execute("SELECT * FROM legacy.hr_leave WHERE request_date_from < %s AND request_date_to >= %s ORDER BY id", [PERIOD_END, PERIOD_START])
        for row in self.cr.dictfetchall():
            if row['id'] in done or row['employee_id'] not in employees or row['holiday_status_id'] not in types:
                continue
            vals = {name: row[name] for name in LEAVE_FIELDS if row.get(name) not in (None, '')}
            vals.update(employee_id=employees[row['employee_id']], holiday_status_id=types[row['holiday_status_id']])
            vals = {key: value for key, value in vals.items() if key in Leave._fields}

            def create_leave(vals=vals, state=row['state']):
                leave = Leave.create(vals)
                # Odoo 19 refuse d'écrire directement un état validé : on rejoue les actions natives.
                if state in ('validate1', 'validate'):
                    leave.sudo().action_approve()
                    if state == 'validate' and leave.state != 'validate':
                        leave.sudo().action_validate()
                elif state == 'refuse':
                    leave.sudo().action_refuse()
                elif state and state != leave.state:
                    leave.write({'state': state})
                if state and leave.state != state:
                    raise ValueError("état %s attendu, %s obtenu" % (state, leave.state))
                return leave

            leave = self.attempt("congé %s" % row['id'], create_leave)
            if leave:
                done[row['id']] = leave.id
                self.remember('hr.leave', row['id'], leave.id)
        log("congés : %s types, %s congé(s) sur la période", len(types), len(done))

    def parameters(self):
        self.cr.execute("SELECT key, value FROM legacy.ir_config_parameter WHERE value <> ''")
        params = self.env['ir.config_parameter'].sudo()
        keys = []
        for key, value in self.cr.fetchall():
            params.set_param(key, value)
            keys.append(key)
        log("paramètres BioTime : %s (mot de passe et jeton non repris)", ", ".join(sorted(keys)))

    def run(self):
        for step in ('departments', 'employees', 'terminals', 'transactions', 'leaves', 'parameters'):
            started = time.monotonic()
            getattr(self, step)()
            self.cr.commit()
            log("étape %s terminée en %.1f s", step, time.monotonic() - started)
        if self.errors:
            log("%s erreur(s) :", len(self.errors))
            for error in self.errors:
                log("  - %s", error)
        else:
            log("aucune erreur")


Loader(env).run()  # noqa: F821 — `env` est fourni par `odoo shell`
