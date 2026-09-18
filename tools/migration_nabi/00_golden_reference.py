# -*- coding: utf-8 -*-
"""M0 — référence du calcul historique nabi_hr (« golden reference »).

À exécuter dans un `odoo shell` **Odoo 18** sur une **copie** de mc2 où nabi_hr est
installé (mc2_golden), jamais sur mc2 ni sur une base Odoo 19.

Le script appelle le contrôleur d'origine tel quel (`portal_get_punch_stacked`)
pour chaque couple employé × mois qui a des pointages :
- 1er appel : la page marquait les doublons « 5 min » pendant l'affichage ;
- 2e appel : celui d'un rechargement de page, c'est lui qui est enregistré ;
- puis retour au point de sauvegarde : la copie reste intacte pour le couple suivant.

Sortie : une ligne JSON par employé × mois dans GOLDEN_OUT. Ce fichier contient des
données personnelles : il reste hors du dépôt git.

Variables d'environnement :
- GOLDEN_OUT   chemin du fichier JSONL (défaut /golden/golden_reference.jsonl)
- GOLDEN_ONLY  essai ciblé : « matricule » ou « matricule:AAAA-MM »

Lancement (depuis l'hôte) :
    docker run --rm -i --network multiceram_default \\
      -v /srv/stacks/multiceram/addons/docs/addons:/mnt/extra-addons:ro \\
      -v /srv/stacks/dev-docker/migration/golden:/golden \\
      odoo:18.0 odoo shell -d mc2_golden --db_host dbProd17 --db_user odoo --db_password odoo18 \\
      --addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/extra-addons --no-http \\
      < tools/migration_nabi/00_golden_reference.py
"""
import json
import os
import time
import traceback
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.addons.nabi_hr.controllers import Attendance as legacy

OUT = os.environ.get('GOLDEN_OUT', '/golden/golden_reference.jsonl')
ONLY = os.environ.get('GOLDEN_ONLY', '').strip()

TOTAL_DURATIONS = (
    'total_normal', 'total_normal2', 'total_pause', 'total_abs', 'total_hs', 'total_hs_corrige',
    'total_hs_declare', 'total_hs25', 'total_hs50', 'total_hs100', 'total_conge', 'total_jf', 'total_jr',
)
TOTAL_COUNTS = ('worked_day', 'jr_absence', 'jr_presence')
DAY_DURATIONS = ('heures_pause', 'heures', 'heures25', 'hs', 'hs25', 'hs50', 'abs25')


class CaptureRequest:
    """Remplace `odoo.http.request` dans le contrôleur : `render` rend les valeurs au lieu du HTML."""

    def __init__(self, environment):
        self.env = environment

    def render(self, template, values):
        return values


def seconds(value):
    return int(value.total_seconds()) if value else 0


def punches(records):
    return [
        {
            'id': punch.id,
            'time': fields.Datetime.to_string(punch.punch_time),
            'usage': punch.terminal_id.usage or None,
            'sens': punch.sens or None,
        }
        for punch in records
    ]


def day_payload(jour, value):
    payload = {name: seconds(value[name]) for name in DAY_DURATIONS}
    payload.update(
        date=str(jour),
        all_punches=punches(value.all_punches),
        clean_punches=punches(value.clean_punches),
        anomalies=[anomaly['code'] for anomaly in (value.anomalies or [])],
        jour_repos_ids=value.jr.ids,
        holiday_ids=value.is_holiday.ids,
        leave_ids=value.is_conge.ids,
    )
    return payload


def pairs_to_compute(cr):
    cr.execute("""
        SELECT t.emp_code, date_trunc('month', t.punch_time)::date AS month
          FROM zk_transaction t
         WHERE t.emp_code IS NOT NULL
           AND EXISTS (SELECT 1 FROM hr_employee e WHERE e.barcode = t.emp_code)
         GROUP BY 1, 2
         ORDER BY 1, 2
    """)
    rows = cr.fetchall()
    if ONLY:
        code, _sep, month = ONLY.partition(':')
        rows = [(c, m) for c, m in rows if c == code and (not month or m.strftime('%Y-%m') == month)]
    return rows


def main(environment):
    # GOLDEN_TZ : fuseau de l'utilisateur simulé (Odoo 19 lit les dates des filtres dans ce fuseau).
    if os.environ.get('GOLDEN_TZ'):
        environment = environment(context=dict(environment.context, tz=os.environ['GOLDEN_TZ']))
    cr = environment.cr
    legacy.request = CaptureRequest(environment)
    legacy.logger.disabled = True  # une ligne de journal par pointage dans le code d'origine
    endpoint = legacy.AttendancePortal.portal_get_punch_stacked
    endpoint = getattr(endpoint, '__wrapped__', endpoint)
    controller = legacy.AttendancePortal()

    rows = pairs_to_compute(cr)
    print("golden: %s couple(s) employé×mois à calculer -> %s" % (len(rows), OUT), flush=True)
    started = time.monotonic()
    errors = 0
    with open(OUT, 'w', encoding='utf-8') as out:
        for index, (code, month) in enumerate(rows, 1):
            start, end = month, month + relativedelta(months=1, days=-1)
            record = {'emp_code': code, 'month': month.strftime('%Y-%m'), 'start': str(start), 'end': str(end)}
            cr.execute("SAVEPOINT golden")
            try:
                kwargs = {'start_day': str(start), 'end_day': str(end), 'emp_id': code}
                endpoint(controller, **kwargs)
                environment.flush_all()
                values = endpoint(controller, **kwargs)
                record['totals'] = {name: seconds(values[name]) for name in TOTAL_DURATIONS}
                record['totals'].update({name: values[name] for name in TOTAL_COUNTS})
                record['days'] = [day_payload(pair.jour, pair.value) for pair in values['pgroupeds']]
            except Exception as exc:  # les plantages du code d'origine font partie de la référence
                errors += 1
                record['error'] = '%s: %s' % (type(exc).__name__, exc)
                record['traceback'] = traceback.format_exc().splitlines()[-4:]
            finally:
                try:
                    environment.flush_all()
                except Exception:
                    pass
                cr.execute("ROLLBACK TO SAVEPOINT golden")
                environment.invalidate_all(flush=False)
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            if index % 100 == 0 or index == len(rows):
                out.flush()
                print("golden: %s/%s (%s erreur(s)) en %.0f s" % (index, len(rows), errors, time.monotonic() - started), flush=True)
    cr.rollback()
    print("golden: terminé, %s erreur(s) du code d'origine enregistrée(s)" % errors, flush=True)


main(env)  # noqa: F821 — `env` est fourni par `odoo shell`
