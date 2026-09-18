# -*- coding: utf-8 -*-
"""M0 (bis) — référence de la page « Anomalies par employé » (vue mc2 n° 2701).

À exécuter comme 00_golden_reference.py : `odoo shell` Odoo 18 sur mc2_golden.

Le contrôleur d'origine (`portal_get_anomalie`) ne faisait que regrouper les pointages
d'un jour par employé ; les règles étaient des expressions QWeb de la vue 2701. Ce script
reprend ce regroupement et évalue ces expressions telles quelles, sur les enregistrements
d'origine, pour chaque jour qui a des pointages.

Sortie : une ligne JSON par jour {day, rows: {matricule: [libellés]}} dans GOLDEN_OUT
(défaut /golden/golden_anomalies.jsonl). GOLDEN_ONLY=AAAA-MM-JJ pour un seul jour.
"""
import json
import os
import time
from datetime import timedelta

OUT = os.environ.get('GOLDEN_OUT', '/golden/golden_anomalies.jsonl')
ONLY = os.environ.get('GOLDEN_ONLY', '').strip()
EXCLUDED_CODES = ['!', '|', ('emp_code', '=like', '9999%'), ('emp_code', '=', '1')]
ROSTER_DOMAIN = [('barcode', '=like', '__%'), '!', '|', ('barcode', '=like', '9999%'), ('barcode', '=', '1')]

# Expressions de la vue 2701, recopiées telles quelles.
Normalized = lambda x: sorted(list(set(x.mapped(lambda x: x.punch_time and x.punch_time.strftime('%H:%M') or '####'))))  # noqa: E731


def labels_for(Punches):
    presence = Normalized(Punches.filtered(lambda x: x.usage == 't' or not x.terminal_id))
    restau = Normalized(Punches.filtered(lambda x: x.usage == 'r'))
    porte = Normalized(Punches.filtered(lambda x: x.usage == 'p'))
    presence_impaire = len(presence) % 2 > 0
    porte_impaire = len(porte) % 2 > 0
    detecte_present = not presence and (restau or porte)
    absente = not Punches
    labels = []
    if absente:
        labels.append("Absent")
    if presence_impaire:
        labels.append("Pointage impaire")
    if detecte_present:
        labels.append("Détecté présent")
    if porte_impaire:
        labels.append("Porte impaire")
    if not (porte_impaire or detecte_present or presence_impaire or absente):
        labels.append("Aucune anomalie")
    return labels


def main(environment):
    cr = environment.cr
    Transaction = environment['zk.transaction']
    Employee = environment['hr.employee']
    cr.execute("SELECT DISTINCT punch_time::date FROM zk_transaction ORDER BY 1")
    days = [row[0] for row in cr.fetchall()]
    if ONLY:
        days = [day for day in days if str(day) == ONLY]
    roster = Employee.search(ROSTER_DOMAIN)
    print("golden anomalies: %s jour(s) -> %s" % (len(days), OUT), flush=True)
    started = time.monotonic()
    with open(OUT, 'w', encoding='utf-8') as out:
        for index, day in enumerate(days, 1):
            domain = [('punch_time', '>=', day), ('punch_time', '<', day + timedelta(days=1))] + EXCLUDED_CODES
            punches = Transaction.search(domain)
            groups = dict((employee, punches.browse()) for employee in roster - punches.mapped('employee_id'))
            groups.update(punches.grouped(lambda x: x.employee_id))
            rows = {}
            for employee, employee_punches in groups.items():
                key = employee.barcode or '__sans_employe__'
                rows[key] = labels_for(employee_punches)
            out.write(json.dumps({'day': str(day), 'rows': rows}, ensure_ascii=False) + "\n")
            if index % 20 == 0 or index == len(days):
                out.flush()
                environment.invalidate_all()
                print("golden anomalies: %s/%s en %.0f s" % (index, len(days), time.monotonic() - started), flush=True)
    cr.rollback()
    print("golden anomalies: terminé", flush=True)


main(env)  # noqa: F821 — `env` est fourni par `odoo shell`
