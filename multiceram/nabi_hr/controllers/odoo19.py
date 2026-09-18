# -*- coding: utf-8 -*-
"""Compatibilité Odoo 19 des filtres de dates de nabi_hr.

Odoo 18 (osv/expression.py) lisait une date, ou une chaîne « AAAA-MM-JJ », comparée à un champ Datetime
sans fuseau : fin de journée pour `>` et `<=`, minuit pour les autres opérateurs.
Odoo 19 (orm/domains.py) la lit dans le fuseau de l'utilisateur : avec un compte en Etc/GMT-1, la page
d'anomalies du 16/02/2026 prenait aussi la dernière heure du 15.
`odoo18_bound` rend aux filtres des contrôleurs leur sens d'origine, sans toucher au reste d'Odoo.
"""
from datetime import date, datetime, time

END_OF_DAY_OPERATORS = ('>', '<=')


def odoo18_bound(value, operator):
    """Borne de filtre telle qu'Odoo 18 la calculait ; datetimes et autres valeurs inchangés."""
    if isinstance(value, str) and len(value) == 10:
        try:
            day = date.fromisoformat(value)
        except ValueError:
            return value
        return datetime.combine(day, time(23, 59, 59) if operator in END_OF_DAY_OPERATORS else time.min)
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime.combine(value, time.max if operator in END_OF_DAY_OPERATORS else time.min)
    return value
