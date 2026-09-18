# -*- coding: utf-8 -*-
"""M3 — parité du calcul historique : moteur Odoo 19 contre la référence d'origine (M0).

À exécuter dans un `odoo shell` Odoo 19 sur la base migrée, fichiers de référence montés
sur /golden (données personnelles, hors dépôt git) :

    docker run --rm -i --network dev-docker_default -e HOST=db -e USER=odoo -e PASSWORD=<PG> \\
      -v /srv/stacks/dev-docker/repos/MultiCeram/multiceram:/mnt/extra-addons/multiceram:ro \\
      -v /srv/stacks/dev-docker/migration/golden:/golden \\
      odoo:19 odoo shell -d multiceram \\
      --addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/extra-addons/multiceram \\
      < tools/migration_nabi/20_parity_legacy.py

Le moteur est alimenté avec les pointages MIGRÉS et les réglages / congés / x_jour_repos
du schéma `legacy`. Chaque écart est classé :
- dev1_copies : le mois contient des transactions importées plusieurs fois par l'ancienne
  synchronisation (fusionnées à la migration, plan §7 DEV-1) ;
- error_match / error_mismatch : la page d'origine plantait (comparé par nature d'erreur) ;
- unexplained : tout le reste, listé en détail.
EMULATE_MAGASIN=1 (défaut) rend aux pointages Magasin leur ancien statut « sans terminal »
pour isoler les autres écarts (DEV-2).
"""
import json
import os
import time
from collections import Counter, defaultdict
from datetime import date

from odoo.addons.itv_zk_attendance.services.legacy_engine import (
    LegacyEmployeeSettings,
    LegacyHoliday,
    LegacyLeave,
    LegacyOvertimeRow,
    LegacyPageError,
    LegacyPunch,
    compute_legacy_page,
    legacy_anomaly_labels,
)
from odoo.addons.itv_zk_connector.services.timeutils import parse_local

GOLDEN_PAGES = os.environ.get('GOLDEN_PAGES', '/golden/golden_reference.jsonl')
GOLDEN_ANOMALIES = os.environ.get('GOLDEN_ANOMALIES', '/golden/golden_anomalies.jsonl')
PARITY_OUT = os.environ.get('PARITY_OUT', '/golden/parity_report.jsonl')
EMULATE_MAGASIN = os.environ.get('EMULATE_MAGASIN', '1') == '1'
SAMPLES = int(os.environ.get('PARITY_SAMPLES', '8'))

TOTALS = {
    'total_normal': 'normal', 'total_normal2': 'normal2', 'total_pause': 'pause', 'total_abs': 'absence',
    'total_hs': 'hs', 'total_hs_corrige': 'hs_corrige', 'total_hs_declare': 'hs_declare',
    'total_hs25': 'hs25', 'total_hs50': 'hs50', 'total_hs100': 'hs100',
}
COUNTS = {'worked_day': 'worked_days', 'jr_absence': 'absence_days', 'jr_presence': 'days'}
DAY_VALUES = {'heures': 'heures', 'heures25': 'heures25', 'heures_pause': 'pause', 'hs': 'hs', 'hs25': 'hs25', 'hs50': 'hs50', 'abs25': 'abs25'}


def log(message, *args):
    print("parité: " + (message % args if args else message), flush=True)


def golden_error_kind(message):
    if message.startswith('IndexError'):
        return LegacyPageError.CARRY_LAST_DAY
    if 'hour must be in' in message:
        return LegacyPageError.ROUND_OVERFLOW
    if 'Expected singleton' in message and 'zk.transaction' in message:
        return LegacyPageError.MULTIPLE_RESTAURANT
    if 'Expected singleton' in message and 'x_jour_repos' in message:
        return LegacyPageError.MULTIPLE_OVERTIME_ROWS
    return 'other:' + message.split(':', 1)[0]


def excluded_code(code):
    return not code or code == '1' or code.startswith('9999')


def load_inputs(cr):
    cr.execute("""
        SELECT p.id, p.emp_code, p.punch_local, t.usage, t.direction, p.duplicate, p.to_delete, p.date_override,
               coalesce(t.is_uhf_bridge, false)
          FROM itv_zk_punch p LEFT JOIN itv_zk_terminal t ON t.id = p.terminal_id
    """)
    punches = defaultdict(list)
    for pid, code, local, usage, direction, duplicate, to_delete, override, uhf in cr.fetchall():
        if usage == 'm' and EMULATE_MAGASIN:
            usage = None
        punches[code].append(LegacyPunch(
            id=pid, local_time=parse_local(local), usage=usage or None,
            direction=direction if direction in ('in', 'out') else None,
            duplicate=bool(duplicate), to_delete=bool(to_delete), date_override=override, uhf_bridge=uhf,
        ))

    cr.execute("SELECT id, barcode, x_horaire, x_day_hour, x_workedday_week, x_pause, x_ignore_uhf, active FROM legacy.hr_employee")
    settings, legacy_ids, roster = {}, {}, set()
    for eid, barcode, horaire, day_hour, week, pause, ignore_uhf, active in cr.fetchall():
        week = int(week) if str(week or '').strip().isdigit() else None
        settings[barcode] = LegacyEmployeeSettings(
            schedule_type=horaire or None, day_hours=day_hour or None, week_hours=week,
            auto_pause=bool(pause), ignore_uhf=bool(ignore_uhf))
        legacy_ids[barcode] = eid
        if active and barcode and len(barcode) >= 2 and not excluded_code(barcode):
            roster.add(barcode)

    cr.execute("SELECT id, employee_id, request_date_from, request_date_to FROM legacy.hr_leave")
    leaves = defaultdict(list)
    for lid, eid, date_from, date_to in cr.fetchall():
        leaves[eid].append(LegacyLeave(id=lid, date_from=date_from, date_to=date_to))

    cr.execute("SELECT x_employee_id, x_date, x_hs_corrige, x_hs_25, x_hs_50, x_hs_100 FROM legacy.x_jour_repos")
    overtime = defaultdict(lambda: defaultdict(list))
    for eid, day, corrige, hs25, hs50, hs100 in cr.fetchall():
        overtime[eid][day].append(LegacyOvertimeRow(hs_corrige=corrige or 0.0, hs_25=hs25 or 0.0, hs_50=hs50 or 0.0, hs_100=hs100 or 0.0))

    cr.execute("SELECT date_from, date_to FROM legacy.resource_calendar_leaves WHERE resource_id IS NULL")
    holidays = [LegacyHoliday(date_from=date_from, date_to=date_to) for date_from, date_to in cr.fetchall()]

    cr.execute("""
        SELECT DISTINCT x.emp_code, to_char(x.punch_time, 'YYYY-MM')
          FROM legacy.zk_transaction x
          JOIN (SELECT tid FROM legacy.zk_transaction WHERE terminal_sn IS DISTINCT FROM 'manual' GROUP BY tid HAVING count(*) > 1) r
            ON r.tid = x.tid
    """)
    copy_months = set(cr.fetchall())
    return punches, settings, legacy_ids, roster, leaves, overtime, holidays, copy_months


def seconds(value):
    return int(value.total_seconds())


def compare_page(record, page):
    diffs = []
    for golden_key, attribute in TOTALS.items():
        engine_value = seconds(getattr(page.totals, attribute))
        if record['totals'][golden_key] != engine_value:
            diffs.append((golden_key, record['totals'][golden_key], engine_value))
    for golden_key, attribute in COUNTS.items():
        engine_value = getattr(page.totals, attribute)
        if record['totals'][golden_key] != engine_value:
            diffs.append((golden_key, record['totals'][golden_key], engine_value))
    for golden_day, engine_day in zip(record['days'], page.days):
        prefix = golden_day['date']
        for golden_key, attribute in DAY_VALUES.items():
            engine_value = seconds(getattr(engine_day, attribute))
            if golden_day[golden_key] != engine_value:
                diffs.append(('%s.%s' % (prefix, golden_key), golden_day[golden_key], engine_value))
        if list(golden_day['anomalies']) != list(engine_day.anomalies):
            diffs.append(('%s.anomalies' % prefix, golden_day['anomalies'], list(engine_day.anomalies)))
        if bool(golden_day['holiday_ids']) != engine_day.holiday:
            diffs.append(('%s.holiday' % prefix, bool(golden_day['holiday_ids']), engine_day.holiday))
        if sorted(golden_day['leave_ids']) != sorted(engine_day.leave_ids):
            diffs.append(('%s.leaves' % prefix, golden_day['leave_ids'], list(engine_day.leave_ids)))
    return diffs


def check_pages(inputs, out):
    punches, settings, legacy_ids, _roster, leaves, overtime, holidays, copy_months = inputs
    statuses, samples, started = Counter(), [], time.monotonic()
    with open(GOLDEN_PAGES, encoding='utf-8') as golden:
        for line in golden:
            record = json.loads(line)
            code, month = record['emp_code'], record['month']
            start, end = date.fromisoformat(record['start']), date.fromisoformat(record['end'])
            eid = legacy_ids.get(code)
            engine_error, page = None, None
            try:
                page = compute_legacy_page(
                    start, end, punches.get(code, []), settings.get(code, LegacyEmployeeSettings()),
                    holidays=holidays, leaves=leaves.get(eid, []), overtime_rows=overtime.get(eid, {}))
            except LegacyPageError as exc:
                engine_error = exc.kind
            golden_error = golden_error_kind(record['error']) if record.get('error') else None
            diffs = []
            if golden_error or engine_error:
                status = 'error_match' if golden_error == engine_error else 'error_mismatch'
                if status == 'error_mismatch':
                    diffs.append(('error', golden_error, engine_error))
            else:
                diffs = compare_page(record, page)
                status = 'match' if not diffs else ('dev1_copies' if (code, month) in copy_months else 'unexplained')
            statuses[status] += 1
            if status in ('unexplained', 'error_mismatch') and len(samples) < SAMPLES:
                samples.append((month, status, diffs[:4]))
            out.write(json.dumps({'kind': 'page', 'emp_code': code, 'month': month, 'status': status, 'diffs': diffs[:40]}, ensure_ascii=False, default=str) + "\n")
    log("pages employé×mois : %s en %.0f s", dict(statuses), time.monotonic() - started)
    for month, status, diffs in samples:
        log("  exemple %s %s : %s", status, month, diffs)
    return statuses


def check_anomalies(inputs, out):
    punches, _settings, _legacy_ids, roster, _leaves, _overtime, _holidays, _copies = inputs
    by_day = defaultdict(lambda: defaultdict(list))
    for code, items in punches.items():
        if excluded_code(code):
            continue
        for punch in items:
            by_day[punch.local_time.date()][code].append(punch)
    statuses, samples = Counter(), []
    with open(GOLDEN_ANOMALIES, encoding='utf-8') as golden:
        for line in golden:
            record = json.loads(line)
            day = date.fromisoformat(record['day'])
            engine_rows = {code: list(legacy_anomaly_labels([])) for code in roster}
            engine_rows.update({code: list(legacy_anomaly_labels(items)) for code, items in by_day[day].items()})
            for code in set(record['rows']) | set(engine_rows):
                golden_labels, engine_labels = record['rows'].get(code), engine_rows.get(code)
                if golden_labels == engine_labels:
                    statuses['match'] += 1
                    continue
                statuses['mismatch'] += 1
                if len(samples) < SAMPLES:
                    samples.append((record['day'], golden_labels, engine_labels))
                out.write(json.dumps({'kind': 'anomaly', 'day': record['day'], 'emp_code': code, 'golden': golden_labels, 'engine': engine_labels}, ensure_ascii=False) + "\n")
    log("lignes anomalies jour×employé : %s", dict(statuses))
    for day, golden_labels, engine_labels in samples:
        log("  exemple %s : référence=%s moteur=%s", day, golden_labels, engine_labels)
    return statuses


def main(environment):
    started = time.monotonic()
    inputs = load_inputs(environment.cr)
    log("entrées chargées en %.0f s (%s matricules avec pointages, Magasin émulé=%s)", time.monotonic() - started, len(inputs[0]), EMULATE_MAGASIN)
    with open(PARITY_OUT, 'w', encoding='utf-8') as out:
        if os.path.exists(GOLDEN_PAGES):
            check_pages(inputs, out)
        else:
            log("référence des pages absente : %s", GOLDEN_PAGES)
        if os.path.exists(GOLDEN_ANOMALIES):
            check_anomalies(inputs, out)
        else:
            log("référence des anomalies absente : %s", GOLDEN_ANOMALIES)
    environment.cr.rollback()
    log("détail : %s", PARITY_OUT)


main(env)  # noqa: F821 — `env` est fourni par `odoo shell`
