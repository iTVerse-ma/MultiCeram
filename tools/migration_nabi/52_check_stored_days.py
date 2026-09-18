# -*- coding: utf-8 -*-
"""M3 bis — journées stockées (itv.attendance.day) contre la référence d'origine (M0), par employé × mois.

Totaux du pied de page et comptes de jours comparés à la seconde près ; mois plantés comparés au drapeau lg_error.
Lecture seule. Lancement comme 20_parity_legacy.py (conteneur odoo:19 ponctuel, /golden monté).
"""
import json
from collections import Counter

GOLDEN = '/golden/golden_reference.jsonl'
TOTALS = {
    'total_normal': 'lg_heures', 'total_normal2': 'lg_heures25', 'total_pause': 'lg_pause', 'total_abs': 'lg_abs25',
    'total_hs': 'lg_hs', 'total_hs_corrige': 'lg_hs25', 'total_hs_declare': 'lg_total_hs_declare',
    'total_hs25': 'lg_total_hs25', 'total_hs50': 'lg_total_hs50', 'total_hs100': 'lg_total_hs100',
}
COUNTS = {'worked_day': 'lg_worked_day', 'jr_absence': 'lg_absent_day'}

cr = env.cr  # noqa: F821
cr.execute("SELECT barcode, id FROM hr_employee WHERE barcode IS NOT NULL")
employees = dict(cr.fetchall())
columns = list(TOTALS.values()) + list(COUNTS.values())
cr.execute("SELECT employee_id, to_char(lg_period, 'YYYY-MM'), count(*), count(lg_error), %s FROM itv_attendance_day GROUP BY 1, 2"
           % ", ".join("sum(%s)" % column for column in columns))
stored = {(row[0], row[1]): row[2:] for row in cr.fetchall()}

status, samples = Counter(), []
with open(GOLDEN) as handle:
    for line in handle:
        record = json.loads(line)
        key = (employees.get(record['emp_code']), record['month'][:7])
        row = stored.get(key)
        if row is None:
            status['missing'] += 1
            samples.append(('missing', record['emp_code'], record['month']))
            continue
        days, errors, values = row[0], row[1], row[2:]
        if record.get('error'):
            status['error_match' if errors == days else 'error_mismatch'] += 1
            continue
        diffs = []
        for index, golden_key in enumerate(TOTALS):
            if abs(float(values[index] or 0) * 3600 - record['totals'][golden_key]) > 1:
                diffs.append((golden_key, record['totals'][golden_key], round(float(values[index] or 0) * 3600)))
        for offset, golden_key in enumerate(COUNTS):
            if int(values[len(TOTALS) + offset] or 0) != record['totals'][golden_key]:
                diffs.append((golden_key, record['totals'][golden_key], values[len(TOTALS) + offset]))
        if record['totals']['jr_presence'] != days:
            diffs.append(('jr_presence', record['totals']['jr_presence'], days))
        if errors:
            diffs.append(('unexpected_error_days', 0, errors))
        status['match' if not diffs else 'mismatch'] += 1
        if diffs and len(samples) < 10:
            samples.append((record['emp_code'], record['month'], diffs[:5]))

print("journées stockées vs référence :", dict(status), "mois stockés :", len(stored), flush=True)
for sample in samples[:10]:
    print("  ", sample, flush=True)
cr.rollback()
