# -*- coding: utf-8 -*-
"""Compare deux sorties de 00_golden_reference.py (Odoo 18 d'origine / nabi_hr porté sur Odoo 19).

Clé : matricule × mois. Égalité exigée sur : présence et type d'erreur, totaux, puis pour chaque jour
les durées, anomalies, pointages (identifiants d'origine conservés par la copie 40), et le NOMBRE de
jours de repos / fériés / congés (leurs identifiants changent à la copie).

    docker run --rm -i -v /srv/stacks/dev-docker/migration/golden:/golden --entrypoint python3 odoo:19 - \\
      /golden/golden_reference.jsonl /golden/golden_reference_nabi19_full.jsonl < tools/migration_nabi/51_compare_reports.py
"""
import collections
import json
import sys


def load(path):
    with open(path, encoding='utf-8') as source:
        return {(item['emp_code'], item['month']): item for item in map(json.loads, source)}


def normalized_day(day):
    day = dict(day)
    for key in ('jour_repos_ids', 'holiday_ids', 'leave_ids'):
        day[key] = len(day.get(key) or [])
    # Copies identiques d'un même pointage (réimports de l'ancienne synchro) : l'ordre entre elles n'est pas
    # déterminé, on compare donc heure, usage et sens plutôt que l'identifiant.
    for key in ('all_punches', 'clean_punches'):
        day[key] = [(punch['time'], punch['usage'], punch['sens']) for punch in day.get(key) or []]
    return day


def outcome(item):
    if 'error' in item:
        return ('error', item['error'].split(':', 1)[0])
    return ('ok', item['totals'], [normalized_day(day) for day in item['days']])


reference, candidate = load(sys.argv[1]), load(sys.argv[2])
stats = collections.Counter()
samples = collections.defaultdict(list)
for key in sorted(set(reference) | set(candidate)):
    if key not in candidate or key not in reference:
        stats['missing_in_' + ('candidate' if key not in candidate else 'reference')] += 1
        continue
    left, right = outcome(reference[key]), outcome(candidate[key])
    if left == right:
        stats['identical_error' if left[0] == 'error' else 'identical'] += 1
        continue
    if left[0] != right[0] or left[0] == 'error':
        kind = 'error_mismatch'
    elif left[1] != right[1]:
        kind = 'totals_differ'
    else:
        kind = 'days_differ'
    stats[kind] += 1
    if len(samples[kind]) < 5:
        detail = {'key': key, 'odoo18': left[:2] if left[0] == 'ok' else left, 'odoo19': right[:2] if right[0] == 'ok' else right}
        if kind == 'days_differ':
            for a, b in zip(left[2], right[2]):
                if a != b:
                    detail['day'] = {k: (a.get(k), b.get(k)) for k in set(a) | set(b) if a.get(k) != b.get(k)}
                    break
        samples[kind].append(detail)
print("employé × mois :", sum(stats.values()), dict(stats))
for kind, items in samples.items():
    print("exemples", kind)
    for item in items:
        print("  ", json.dumps(item, ensure_ascii=False, default=str)[:600])
