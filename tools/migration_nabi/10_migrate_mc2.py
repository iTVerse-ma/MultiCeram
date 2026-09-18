# -*- coding: utf-8 -*-
"""M2 — migration des données MultiCeram (mc2, Odoo 18) vers une base Odoo 19.

À exécuter dans un `odoo shell` Odoo 19 (dev-docker) sur une base où itv_zk_connector
est installé et où le schéma `legacy` contient les tables copiées de mc2 (étape M1).

Rejouable : les correspondances « ancien id → nouvel id » sont gardées dans
legacy.itv_map ; les pointages sont insérés en « ON CONFLICT DO NOTHING ».

Variable STEPS (ordre imposé, défaut : toutes) :
    backend, departments, employees, settings, terminals, punches, leaves, overtime, schedules
« settings » compte le Magasin comme présence et met les mois en file : sur une base neuve, le lancer
seul après « punches » (STEPS=settings), puis « overtime,schedules » une fois les journées recalculées.

Reporté aux phases suivantes du plan :
- PIN CVSecurity x_acc_pin (module CVSecurity) ;
- comptes portail des employés (phase A5).

Lancement (depuis /srv/stacks/dev-docker) :
    docker compose exec -T -e STEPS=backend,departments odoo odoo shell -c /etc/odoo/odoo.conf \\
      -d multiceram --db_host db --db_user odoo --db_password <PG_PASSWORD> < 10_migrate_mc2.py
"""
import os
import time

from psycopg2.extras import execute_values

from odoo import fields
from odoo.addons.itv_zk_connector.services.timeutils import local_to_utc, parse_local

TZ = 'Africa/Casablanca'
ALL_STEPS = ('backend', 'departments', 'employees', 'settings', 'terminals', 'punches', 'leaves', 'overtime', 'schedules')
MAGASIN_SN = 'NYU7243300081'
BATCH = 5000
REPRISE_ALLOCATION = "Reprise historique mc2"
EMPLOYEE_FIELDS = (
    'job_title', 'work_email', 'work_phone', 'mobile_phone', 'private_email', 'private_phone',
    'birthday', 'ssnid', 'employee_type', 'place_of_birth', 'marital',
    'private_street', 'private_street2', 'private_city', 'private_zip',
)
LEAVE_FIELDS = (
    'request_date_from', 'request_date_to', 'request_date_from_period', 'request_unit_half',
    'request_unit_hours', 'request_hour_from', 'request_hour_to', 'private_name', 'notes',
)


def log(message, *args):
    print("migration: " + (message % args if args else message), flush=True)


def text(value):
    """Champ traduisible (jsonb) ou texte simple → texte, français d'abord."""
    if isinstance(value, dict):
        return value.get('fr_FR') or value.get('en_US') or next(iter(value.values()), '')
    return value or ''


class Migration:

    def __init__(self, environment):
        self.env = environment(context=dict(
            environment.context,
            active_test=False,
            tracking_disable=True,
            mail_create_nolog=True,
            mail_create_nosubscribe=True,
            mail_notrack=True,
        ))
        self.cr = self.env.cr
        self.company = self.env.company
        self.errors = []
        self.skipped = []
        self.cr.execute("""
            CREATE TABLE IF NOT EXISTS legacy.itv_map (
                model varchar NOT NULL,
                legacy_id integer NOT NULL,
                new_id integer NOT NULL,
                PRIMARY KEY (model, legacy_id)
            )
        """)
        self.backend = self.env['itv.zk.backend']

    # -- Correspondances ---------------------------------------------------------

    def mapped(self, model):
        self.cr.execute("SELECT legacy_id, new_id FROM legacy.itv_map WHERE model = %s", [model])
        return dict(self.cr.fetchall())

    def remember(self, model, legacy_id, new_id):
        self.cr.execute("""
            INSERT INTO legacy.itv_map (model, legacy_id, new_id) VALUES (%s, %s, %s)
            ON CONFLICT (model, legacy_id) DO UPDATE SET new_id = EXCLUDED.new_id
        """, [model, legacy_id, new_id])

    def attempt(self, label, function):
        """Exécute une création isolée ; une erreur est consignée sans arrêter l'étape."""
        try:
            with self.cr.savepoint():
                return function()
        except Exception as exc:  # consigné dans le rapport de migration
            self.errors.append("%s : %s" % (label, exc))
            return None

    # -- Étapes ------------------------------------------------------------------------

    def step_backend(self):
        self.cr.execute("SELECT key, value FROM legacy.ir_config_parameter")
        params = dict(self.cr.fetchall())
        url = params.get('zk.server') or 'http://biotime.invalid/'
        Backend = self.env['itv.zk.backend']
        backend = Backend.search([('url', '=', url)], limit=1)
        if not backend:
            # Inactive et en lecture seule tant que l'accès réseau au BioTime du client n'existe pas ;
            # le mot de passe est ressaisi, jamais copié.
            backend = Backend.create({
                'name': "BioTime MultiCeram",
                'url': url,
                'username': params.get('zk.user') or False,
                'timezone': TZ,
                'read_only': True,
                'active': False,
                'company_id': self.company.id,
            })
        self.backend = backend
        log("connexion BioTime : %s (%s, active=%s, lecture seule=%s)", backend.name, backend.url, backend.active, backend.read_only)

    def _require_backend(self):
        if not self.backend:
            self.backend = self.env['itv.zk.backend'].search([('name', '=', "BioTime MultiCeram")], limit=1)
        if not self.backend:
            raise RuntimeError("Connexion BioTime absente : lancer d'abord l'étape « backend ».")

    def step_departments(self):
        Department = self.env['hr.department']
        done = self.mapped('hr.department')
        self.cr.execute("SELECT id, name, parent_id, active FROM legacy.hr_department ORDER BY parent_path NULLS FIRST, id")
        rows = self.cr.dictfetchall()
        created = 0
        for row in rows:
            if row['id'] in done:
                continue
            department = self.attempt("département %s" % row['id'], lambda row=row: Department.create({
                'name': text(row['name']) or "Département %s" % row['id'],
                'active': bool(row['active']),
                'company_id': self.company.id,
            }))
            if department:
                done[row['id']] = department.id
                self.remember('hr.department', row['id'], department.id)
                created += 1
        for row in rows:
            if row['parent_id'] in done and row['id'] in done:
                Department.browse(done[row['id']]).parent_id = done[row['parent_id']]
        log("départements : %s créés, %s au total", created, len(done))

    def step_employees(self):
        Employee = self.env['hr.employee']
        departments = self.mapped('hr.department')
        done = self.mapped('hr.employee')
        self.cr.execute("""
            SELECT e.*, r.tz AS resource_tz
              FROM legacy.hr_employee e
              LEFT JOIN legacy.resource_resource r ON r.id = e.resource_id
             ORDER BY e.id
        """)
        rows = self.cr.dictfetchall()
        by_barcode = {employee.barcode: employee.id for employee in Employee.search([('barcode', '!=', False)])}
        created = linked = 0
        for row in rows:
            if row['id'] in done:
                continue
            barcode = (row['barcode'] or '').strip() or False
            if barcode and barcode in by_barcode:
                done[row['id']] = by_barcode[barcode]
                self.remember('hr.employee', row['id'], by_barcode[barcode])
                linked += 1
                continue
            vals = {name: row[name] for name in EMPLOYEE_FIELDS if row.get(name)}
            zk_id = (row.get('zk_id') or '').strip()
            vals.update(
                name=text(row['name']) or barcode or "Employé %s" % row['id'],
                barcode=barcode,
                pin=(row['pin'] or '').strip() or False,
                active=bool(row['active']),
                company_id=self.company.id,
                department_id=departments.get(row['department_id'], False),
                tz=row['resource_tz'] or TZ,
                itv_biotime_emp_id=int(zk_id) if zk_id.isdigit() else 0,
            )
            if row.get('gender'):
                vals['sex'] = row['gender']
            # 36 fiches portaient le matricule à la place de la CIN : on ne recopie pas ce faux numéro.
            if row.get('identification_id') and row['identification_id'] != row['barcode']:
                vals['identification_id'] = row['identification_id']
            vals = {key: value for key, value in vals.items() if key in Employee._fields}
            employee = self.attempt("employé %s" % row['id'], lambda vals=vals: Employee.create(vals))
            if employee:
                done[row['id']] = employee.id
                self.remember('hr.employee', row['id'], employee.id)
                created += 1
        hierarchy = 0
        for row in rows:
            if row['id'] not in done:
                continue
            vals = {}
            if row['parent_id'] in done:
                vals['parent_id'] = done[row['parent_id']]
            if row['coach_id'] in done:
                vals['coach_id'] = done[row['coach_id']]
            if vals and self.attempt("hiérarchie employé %s" % row['id'], lambda row=row, vals=vals: Employee.browse(done[row['id']]).write(vals)) is not None:
                hierarchy += 1
        log("employés : %s créés, %s rapprochés par matricule, %s liens hiérarchiques", created, linked, hierarchy)

    def step_settings(self):
        """Réglages du calcul historique (x_horaire, x_day_hour…) → champs itv_* de itv_zk_attendance."""
        Employee = self.env['hr.employee']
        if 'itv_schedule_type' not in Employee._fields:
            raise RuntimeError("Installer itv_zk_attendance avant l'étape « settings ».")
        employees = self.mapped('hr.employee')
        self.cr.execute("SELECT id, x_horaire, x_day_hour, x_workedday_week, x_pause, x_heure_supp, x_ignore_uhf FROM legacy.hr_employee")
        updated = 0
        for row in self.cr.dictfetchall():
            if row['id'] not in employees:
                continue
            week = str(row['x_workedday_week'] or '').strip()
            Employee.browse(employees[row['id']]).with_context(itv_skip_legacy_enqueue=True).write({
                # Horaire vide gardé vide : le calcul historique ne le traite pas comme « normal ».
                'itv_schedule_type': row['x_horaire'] or False,
                'itv_day_hours': row['x_day_hour'] or 0.0,
                'itv_week_hours': int(week) if week.isdigit() else 0,
                'itv_auto_pause': bool(row['x_pause']),
                'itv_overtime_eligible': bool(row['x_heure_supp']),
                'itv_ignore_uhf': bool(row['x_ignore_uhf']),
            })
            updated += 1
        # Les pointages Magasin n'avaient pas de terminal dans nabi_hr et comptaient comme présence (décision 14/09/2026).
        magasin = self.env['itv.zk.terminal'].search([('sn', '=', MAGASIN_SN)])
        magasin.with_context(itv_skip_legacy_enqueue=True).write({'itv_legacy_presence': True})
        queued = self.env['itv.attendance.dirty']._enqueue_from_punches()
        log("réglages de pointage : %s employés, Magasin compté comme présence (%s terminal), %s mois mis en file de recalcul",
            updated, len(magasin), queued)

    def step_terminals(self):
        self._require_backend()
        Terminal = self.env['itv.zk.terminal']
        done = self.mapped('itv.zk.terminal')
        self.cr.execute("SELECT res_id FROM legacy.ir_model_data WHERE module = 'nabi' AND name = 'uhf'")
        uhf_ids = {res_id for (res_id,) in self.cr.fetchall()}
        self.cr.execute("SELECT id, tid, sn, alias, usage, sens, last_activity FROM legacy.zk_terminals ORDER BY id")
        created = 0
        for row in self.cr.dictfetchall():
            if row['id'] in done:
                continue
            serial = (row['sn'] or '').strip()
            terminal = Terminal.search([('backend_id', '=', self.backend.id), ('sn', '=', serial)], limit=1)
            if not terminal:
                tid = (row['tid'] or '').strip() if isinstance(row['tid'], str) else row['tid']
                terminal = Terminal.create({
                    'backend_id': self.backend.id,
                    'sn': serial,
                    'alias': row['alias'] or serial,
                    'usage': row['usage'] or 'unclassified',
                    'direction': row['sens'] or 'none',
                    'biotime_id': int(tid) if str(tid or '').isdigit() else 0,
                    'is_uhf_bridge': row['id'] in uhf_ids,
                    'is_virtual': row['id'] in uhf_ids,
                    'last_activity': local_to_utc(row['last_activity'], TZ) if row['last_activity'] else False,
                })
                created += 1
            done[row['id']] = terminal.id
            self.remember('itv.zk.terminal', row['id'], terminal.id)
        # Le kiosque Magasin pointait sur un terminal absent de zk_terminals (441 pointages sans terminal).
        if not Terminal.search([('backend_id', '=', self.backend.id), ('sn', '=', MAGASIN_SN)], limit=1):
            Terminal.create({'backend_id': self.backend.id, 'sn': MAGASIN_SN, 'alias': "Magasin", 'usage': 'm', 'direction': 'none'})
            created += 1
        log("terminaux : %s créés, %s rapprochés au total (+ Magasin)", created, len(done))

    def step_punches(self):
        self._require_backend()
        backend = self.backend
        terminal_map = self.mapped('itv.zk.terminal')
        terminals = {
            terminal.id: (terminal.usage, terminal.direction, terminal.timezone_override)
            for terminal in self.env['itv.zk.terminal'].search([('backend_id', '=', backend.id)])
        }
        magasin_id = self.env['itv.zk.terminal'].search([('backend_id', '=', backend.id), ('sn', '=', MAGASIN_SN)], limit=1).id
        self.cr.execute("SELECT barcode, id FROM hr_employee WHERE barcode IS NOT NULL")
        employee_ids = dict(self.cr.fetchall())
        self.cr.execute("SELECT emp_code, punch_local FROM itv_zk_punch WHERE backend_id = %s AND source = 'migrated_manual'", [backend.id])
        manual_done = set(self.cr.fetchall())
        seen_device = set()
        stats = dict(read=0, inserted=0, exact_copies=0, manual_already=0, without_id=0)
        now = fields.Datetime.now()
        uid = self.env.uid
        last_id = 0
        started = time.monotonic()
        while True:
            self.cr.execute("""
                SELECT id, terminal_id, tid, emp_code, terminal_sn, terminal_alias, upload_time, punch_time,
                       duplicate, to_delete, x_date_appliquee
                  FROM legacy.zk_transaction
                 WHERE id > %s
                 ORDER BY id
                 LIMIT %s
            """, [last_id, BATCH])
            rows = self.cr.dictfetchall()
            if not rows:
                break
            last_id = rows[-1]['id']
            values = []
            for row in rows:
                stats['read'] += 1
                serial = (row['terminal_sn'] or '').strip()
                tid = str(row['tid'] or '').strip()
                code = (row['emp_code'] or '').strip() or None
                punch_local_dt = row['punch_time']
                punch_local = punch_local_dt.strftime('%Y-%m-%d %H:%M:%S')
                if serial == 'manual':
                    if (code, punch_local) in manual_done:
                        stats['manual_already'] += 1
                        continue
                    manual_done.add((code, punch_local))
                    source, biotime_id, manuallog_id, terminal_id = 'migrated_manual', None, int(tid) if tid.isdigit() else None, None
                else:
                    if not tid.isdigit():
                        stats['without_id'] += 1
                        continue
                    biotime_id = int(tid)
                    if biotime_id in seen_device:
                        stats['exact_copies'] += 1
                        continue
                    seen_device.add(biotime_id)
                    source, manuallog_id = 'device', None
                    terminal_id = terminal_map.get(row['terminal_id']) or (magasin_id if serial == MAGASIN_SN else None)
                usage, direction, tz_override = terminals.get(terminal_id, (None, None, None))
                punch_utc = local_to_utc(punch_local_dt, tz_override or TZ)
                upload_utc, delay = None, 0
                upload = row['upload_time']
                if upload:
                    try:
                        upload_local = upload if not isinstance(upload, str) else parse_local(upload)
                        upload_utc = local_to_utc(upload_local, TZ)
                        delay = int((upload_utc - punch_utc).total_seconds() // 60)
                    except ValueError:
                        upload_utc = None
                values.append((
                    backend.id, self.company.id, source, biotime_id, manuallog_id, code, employee_ids.get(code),
                    punch_local, punch_utc, punch_local_dt.date(), terminal_id, serial or None, row['terminal_alias'] or None,
                    usage, direction, upload_utc, delay, bool(row['duplicate']), 'migrated' if row['duplicate'] else None,
                    bool(row['to_delete']), row['x_date_appliquee'], uid, uid, now, now,
                ))
            if values:
                execute_values(self.cr, """
                    INSERT INTO itv_zk_punch (
                        backend_id, company_id, source, biotime_id, biotime_manuallog_id, emp_code, employee_id,
                        punch_local, punch_time, punch_date, terminal_id, terminal_sn, terminal_alias,
                        usage, direction, upload_time, upload_delay_min, duplicate, duplicate_origin,
                        to_delete, date_override, create_uid, write_uid, create_date, write_date
                    ) VALUES %s
                    ON CONFLICT DO NOTHING
                """, values, page_size=len(values))
                stats['inserted'] += self.cr.rowcount
            self.cr.commit()
            log("pointages : %s lus, %s insérés (%.0f s)", stats['read'], stats['inserted'], time.monotonic() - started)
        # Doublons de page de l'ancienne synchronisation : la même transaction importée plusieurs fois,
        # parfois avec des indicateurs « doublon » différents. Une seule ligne est gardée ; elle reste visible
        # si au moins une copie l'était, comme sur l'ancienne page qui ne filtrait que les lignes marquées.
        self.cr.execute("""
            WITH visible AS (
                SELECT tid::bigint AS biotime_id
                  FROM legacy.zk_transaction
                 WHERE terminal_sn IS DISTINCT FROM 'manual' AND tid ~ '^[0-9]+$'
                 GROUP BY tid::bigint
                HAVING count(*) > 1 AND bool_or(NOT coalesce(duplicate, false))
            )
            UPDATE itv_zk_punch p
               SET duplicate = false, duplicate_origin = NULL
              FROM visible v
             WHERE p.backend_id = %s AND p.source = 'device' AND p.duplicate AND p.biotime_id = v.biotime_id
        """, [backend.id])
        stats['flags_merged'] = self.cr.rowcount
        self.cr.commit()
        self.env['itv.zk.punch'].invalidate_model()
        log("pointages : %s", ", ".join("%s=%s" % item for item in stats.items()))

    def step_leaves(self):
        LeaveType = self.env['hr.leave.type']
        type_map = self.mapped('hr.leave.type')
        employees = self.mapped('hr.employee')
        self.cr.execute("SELECT holiday_status_id, count(*) FROM legacy.hr_leave GROUP BY 1")
        usage = dict(self.cr.fetchall())
        self.cr.execute("""
            SELECT t.*, d.name AS xmlid
              FROM legacy.hr_leave_type t
              LEFT JOIN legacy.ir_model_data d ON d.model = 'hr.leave.type' AND d.res_id = t.id AND d.module = 'hr_holidays'
             ORDER BY t.id
        """)
        for row in self.cr.dictfetchall():
            if row['id'] in type_map:
                continue
            target = self.env.ref('hr_holidays.%s' % row['xmlid'], raise_if_not_found=False) if row['xmlid'] else None
            if not target:
                vals = {
                    'name': text(row['name']),
                    # Sans congé enregistré, le type ne sert qu'à l'historique (ex. « Reste Day ») : archivé.
                    'active': bool(row['active']) and bool(usage.get(row['id'])),
                    'company_id': self.company.id,
                }
                for name in ('leave_validation_type', 'request_unit', 'time_type', 'requires_allocation', 'unpaid'):
                    value = self._convert_field_value(LeaveType, name, row.get(name))
                    if value is not None:
                        vals[name] = value
                target = self.attempt("type de congé %s" % row['id'], lambda vals=vals: LeaveType.create(vals))
            if target:
                type_map[row['id']] = target.id
                self.remember('hr.leave.type', row['id'], target.id)

        leave_map = self.mapped('hr.leave')
        self._create_reprise_allocations(type_map, employees, leave_map)
        Leave = self.env['hr.leave'].with_context(leave_skip_state_check=True, leave_skip_date_check=True)
        self.cr.execute("SELECT * FROM legacy.hr_leave ORDER BY id")
        migrated = 0
        for row in self.cr.dictfetchall():
            if row['id'] in leave_map:
                continue
            if row['employee_id'] not in employees or row['holiday_status_id'] not in type_map:
                self.errors.append("congé %s : employé ou type non migré" % row['id'])
                continue
            target_type = LeaveType.browse(type_map[row['holiday_status_id']])
            if target_type.requires_allocation and not (row['number_of_days'] or row['number_of_hours']):
                # Ex. demande « Congés payés » posée un dimanche, jamais approuvée : 0 jour, aucune attribution possible.
                self.skipped.append("congé %s (%s, %s → %s, état %s) : durée nulle sur un type soumis à attribution"
                                    % (row['id'], text(target_type.name), row['request_date_from'], row['request_date_to'], row['state']))
                continue
            vals = {name: row[name] for name in LEAVE_FIELDS if row.get(name) not in (None, '')}
            vals.update(employee_id=employees[row['employee_id']], holiday_status_id=type_map[row['holiday_status_id']])
            vals = {key: value for key, value in vals.items() if key in Leave._fields}

            def create_leave(vals=vals, state=row['state']):
                leave = Leave.create(vals)
                if state and state != leave.state:
                    leave.write({'state': state})
                return leave

            leave = self.attempt("congé %s" % row['id'], create_leave)
            if leave:
                self.remember('hr.leave', row['id'], leave.id)
                migrated += 1

        Holiday = self.env['resource.calendar.leaves']
        holiday_map = self.mapped('resource.calendar.leaves')
        self.cr.execute("""
            SELECT id, name, date_from, date_to, time_type
              FROM legacy.resource_calendar_leaves
             WHERE resource_id IS NULL AND holiday_id IS NULL
             ORDER BY id
        """)
        holidays = 0
        for row in self.cr.dictfetchall():
            if row['id'] in holiday_map:
                continue
            existing = Holiday.search([('resource_id', '=', False), ('name', '=', row['name']), ('date_from', '=', row['date_from'])], limit=1)
            holiday = existing or self.attempt("jour férié %s" % row['id'], lambda row=row: Holiday.create({
                'name': row['name'],
                'date_from': row['date_from'],
                'date_to': row['date_to'],
                'time_type': row['time_type'] or 'leave',
                'company_id': self.company.id,
            }))
            if holiday:
                self.remember('resource.calendar.leaves', row['id'], holiday.id)
                holidays += 1
        log("congés : %s types rapprochés, %s congés migrés, %s jours fériés", len(type_map), migrated, holidays)

    def step_overtime(self):
        """x_jour_repos → heures supplémentaires proposées dans Présences (circuit N1 / N2).

        nabi_hr ne remplissait que x_hs (heures envoyées depuis la page) : elles deviennent des propositions,
        hors totaux « déclaré » tant qu'elles ne sont pas mises en circuit. Les jours de repos sont repris à part.
        """
        Line = self.env['hr.attendance.overtime.line']
        if 'itv_state' not in Line._fields:
            raise RuntimeError("Mettre à jour itv_zk_attendance avant l'étape « overtime ».")
        employees = self.mapped('hr.employee')
        done = self.mapped('x_jour_repos')
        rest_done = self.mapped('x_jour_repos.rest_day')
        rest_type = self.env.ref('itv_zk_attendance.leave_type_rest_day')
        Leave = self.env['hr.leave']
        Day = self.env['itv.attendance.day']
        self.cr.execute("""
            SELECT id, x_employee_id, x_date, x_jour_repos, x_hs, x_hs_corrige, x_hs_25, x_hs_50, x_hs_100, x_validation_1, x_validation_2
              FROM legacy.x_jour_repos ORDER BY id
        """)
        created = rest_days = 0
        for row in self.cr.dictfetchall():
            if row['id'] in done or row['id'] in rest_done:
                continue
            label = "x_jour_repos %s (%s)" % (row['id'], row['x_date'])
            if row['x_employee_id'] not in employees:
                self.errors.append("%s : employé non migré" % label)
                continue
            if row['x_jour_repos']:
                # Colonne JR de la page d'origine → congé natif « Jour de repos », validé d'office.
                leave = self.attempt(label, lambda row=row: Leave.create({
                    'employee_id': employees[row['x_employee_id']],
                    'holiday_status_id': rest_type.id,
                    'request_date_from': row['x_date'],
                    'request_date_to': row['x_date'],
                }))
                if leave:
                    self.remember('x_jour_repos.rest_day', row['id'], leave.id)
                    rest_days += 1
                continue
            if any(row[name] for name in ('x_hs_corrige', 'x_hs_25', 'x_hs_50', 'x_hs_100')):
                self.errors.append("%s : heures déclarées ou ventilées, cas absent de mc2 au 15/09/2026" % label)
                continue
            if not row['x_hs'] or row['x_hs'] <= 0:
                validated = " (validée N1/N2 sans heures)" if row['x_validation_1'] or row['x_validation_2'] else ""
                self.skipped.append("%s : aucune heure proposée%s" % (label, validated))
                continue
            employee_id = employees[row['x_employee_id']]
            day = Day.search([('employee_id', '=', employee_id), ('date', '=', row['x_date'])], limit=1)
            attendance = day.attendance_ids[:1]
            line = self.attempt(label, lambda row=row, employee_id=employee_id, day=day, attendance=attendance: Line.create({
                'employee_id': employee_id,
                'date': row['x_date'],
                'duration': row['x_hs'],
                'itv_rate': '25',
                'itv_state': 'draft',
                'itv_day_id': day.id or False,
                'time_start': attendance.check_in or False,
                'time_stop': attendance.check_out or False,
            }))
            if line:
                self.remember('x_jour_repos', row['id'], line.id)
                created += 1
        log("heures supplémentaires : %s proposition(s) créée(s) ; jours de repos : %s congé(s) créé(s)", created, rest_days)

    def step_schedules(self):
        """Horaires de travail natifs selon les réglages nabi_hr (choix du 15/09/2026) : poste et sécurité flexibles,
        « Normal 44 h » si 44 heures par semaine, sinon « Normal 48 h », profil vide compris."""
        employees = self.env['hr.employee'].with_context(active_test=False).browse(list(self.mapped('hr.employee').values()))
        changed = employees._itv_apply_profile_calendar()
        counts = {}
        for employee in employees.sudo():
            counts[employee.resource_calendar_id.name] = counts.get(employee.resource_calendar_id.name, 0) + 1
        log("horaires de travail : %s employé(s) mis à jour ; %s", len(changed),
            " ; ".join("%s = %s" % item for item in sorted(counts.items())))

    def _create_reprise_allocations(self, type_map, employees, leave_map):
        """Attributions « Reprise historique » : nabi_hr désactivait le contrôle de solde, Odoo 19 l'impose.

        Une attribution validée par employé et par type couvre exactement les jours des congés repris.
        """
        Allocation = self.env['hr.leave.allocation']
        LeaveType = self.env['hr.leave.type']
        self.cr.execute("SELECT id, employee_id, holiday_status_id, number_of_days, number_of_hours, request_date_from FROM legacy.hr_leave ORDER BY id")
        needed = {}
        for row in self.cr.dictfetchall():
            if row['id'] in leave_map or row['employee_id'] not in employees or row['holiday_status_id'] not in type_map:
                continue
            leave_type = LeaveType.browse(type_map[row['holiday_status_id']])
            if not leave_type.requires_allocation or not (row['number_of_days'] or row['number_of_hours']):
                continue
            key = (employees[row['employee_id']], leave_type.id)
            days, start = needed.get(key, (0.0, row['request_date_from']))
            needed[key] = (days + (row['number_of_days'] or 0.0), min(start, row['request_date_from']))
        created = 0
        for (employee_id, type_id), (days, start) in needed.items():
            if Allocation.search_count([('employee_id', '=', employee_id), ('holiday_status_id', '=', type_id), ('name', '=', REPRISE_ALLOCATION)]):
                continue

            def create_allocation(employee_id=employee_id, type_id=type_id, days=days, start=start):
                allocation = Allocation.create({
                    'name': REPRISE_ALLOCATION,
                    'employee_id': employee_id,
                    'holiday_status_id': type_id,
                    'number_of_days': days,
                    'date_from': start,
                    'allocation_type': 'regular',
                })
                if allocation.state != 'validate':
                    allocation.action_approve()
                if allocation.state != 'validate':
                    allocation._action_validate()
                return allocation

            if self.attempt("attribution de reprise employé %s / type %s" % (employee_id, type_id), create_allocation):
                created += 1
        log("attributions de reprise : %s créées pour %s couple(s) employé × type", created, len(needed))

    @staticmethod
    def _convert_field_value(model, name, value):
        """Adapte une valeur Odoo 18 au type du champ Odoo 19 (ex. requires_allocation yes/no → booléen)."""
        field = model._fields.get(name)
        if field is None or value is None:
            return None
        if field.type == 'boolean':
            return value in (True, 'yes', 'True', 't') if not isinstance(value, bool) else value
        if field.type == 'selection':
            keys = {key for key, _label in field._description_selection(model.env)}
            if isinstance(value, bool):
                value = 'yes' if value else 'no'
            return value if value in keys else None
        return value

    # -- Exécution ------------------------------------------------------------------------

    def run(self, steps):
        for step in ALL_STEPS:
            if step not in steps:
                continue
            started = time.monotonic()
            log("--- étape %s ---", step)
            getattr(self, 'step_%s' % step)()
            self.cr.commit()
            log("étape %s terminée en %.1f s", step, time.monotonic() - started)
        if self.skipped:
            log("%s élément(s) volontairement non repris :", len(self.skipped))
            for item in self.skipped:
                log("  - %s", item)
        if self.errors:
            log("%s erreur(s) :", len(self.errors))
            for error in self.errors:
                log("  - %s", error)
        else:
            log("aucune erreur")


requested = [step.strip() for step in os.environ.get('STEPS', ','.join(ALL_STEPS)).split(',') if step.strip()]
unknown = set(requested) - set(ALL_STEPS)
if unknown:
    raise SystemExit("Étapes inconnues : %s" % ", ".join(sorted(unknown)))
Migration(env).run(requested)  # noqa: F821 — `env` est fourni par `odoo shell`
