# -*- coding: utf-8 -*-
"""Parité de la page « Gestion des anomalies » du nabi_hr porté (Odoo 19) avec la référence Odoo 18.

Appelle le contrôleur porté (`portal_get_anomalie`) pour chaque jour de la référence
01_golden_anomalies.py, sous le fuseau d'un vrai compte (Odoo 19 lit les dates des filtres
dans ce fuseau), puis évalue les libellés de la vue d'origine (mêmes expressions que 01).
À exécuter sur multiceram_nabi (données complètes) ; lecture seule (retour arrière final).

Variables : PARITY_TZ (défaut Etc/GMT-1, fuseau de admin dans mc2), GOLDEN_ANOMALIES,
PARITY_OUT (écarts détaillés, JSONL), GOLDEN_ONLY=AAAA-MM-JJ.

    docker run --rm -i --network dev-docker_default -e HOST=db -e USER=odoo -e PASSWORD=<PG> \\
      -v /srv/stacks/dev-docker/repos/MultiCeram/multiceram:/mnt/extra-addons/multiceram:ro \\
      -v /srv/stacks/dev-docker/migration/golden:/golden \\
      odoo:19 odoo shell -d multiceram_nabi \\
      --addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/extra-addons/multiceram \\
      < tools/migration_nabi/50_parity_port_anomalies.py
"""
import json
import os
import time
from datetime import date

from odoo.addons.nabi_hr.controllers import Attendance as legacy

TZ = os.environ.get('PARITY_TZ', 'Etc/GMT-1')
GOLDEN = os.environ.get('GOLDEN_ANOMALIES', '/golden/golden_anomalies.jsonl')
OUT = os.environ.get('PARITY_OUT', '/golden/parity_port_anomalies.jsonl')
ONLY = os.environ.get('GOLDEN_ONLY', '').strip()

Normalized = lambda x: sorted(list(set(x.mapped(lambda x: x.punch_time and x.punch_time.strftime('%H:%M') or '####'))))  # noqa: E731


def labels_for(Punches):
    """Expressions de la vue 2701, identiques à 01_golden_anomalies.py."""
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


class CaptureRequest:
    """Remplace `odoo.http.request` : `render` rend les valeurs au lieu du HTML."""

    def __init__(self, environment):
        self.env = environment

    def render(self, template, values):
        return values


def main(shell_env):
    environment = shell_env(context=dict(shell_env.context, tz=TZ, lang='fr_FR'))
    legacy.request = CaptureRequest(environment)
    endpoint = legacy.AttendancePortal.portal_get_anomalie
    endpoint = getattr(endpoint, '__wrapped__', endpoint)
    controller = legacy.AttendancePortal()
    with open(GOLDEN, encoding='utf-8') as source:
        golden = [json.loads(line) for line in source]
    if ONLY:
        golden = [item for item in golden if item['day'] == ONLY]
    started = time.monotonic()
    days_ok = rows_total = rows_diff = leaked_days = 0
    with open(OUT, 'w', encoding='utf-8') as out:
        for index, item in enumerate(golden, 1):
            day = date.fromisoformat(item['day'])
            values = endpoint(controller, start_day=item['day'])
            groups = values['portal_punches']
            extra_keys = sorted(str(key) for key in groups if key != day)
            rows = {}
            for employee, punches in groups.get(day, {}).items():
                rows[employee.barcode or '__sans_employe__'] = labels_for(punches)
            differences = {code: {'odoo18': item['rows'].get(code), 'odoo19': rows.get(code)}
                           for code in set(item['rows']) | set(rows) if item['rows'].get(code) != rows.get(code)}
            rows_total += len(item['rows'])
            rows_diff += len(differences)
            leaked_days += bool(extra_keys)
            if differences or extra_keys:
                out.write(json.dumps({'day': item['day'], 'other_days_shown': extra_keys, 'differences': differences}, ensure_ascii=False) + "\n")
            else:
                days_ok += 1
            if index % 20 == 0 or index == len(golden):
                environment.invalidate_all()
                print("parité anomalies: %s/%s jours, %s identiques, %s ligne(s) différente(s) sur %s, %s jour(s) débordant sur un autre, %.0f s"
                      % (index, len(golden), days_ok, rows_diff, rows_total, leaked_days, time.monotonic() - started), flush=True)
    environment.cr.rollback()
    print("parité anomalies: terminé (fuseau %s) -> %s" % (TZ, OUT), flush=True)


main(env)  # noqa: F821 — `env` est fourni par `odoo shell`
