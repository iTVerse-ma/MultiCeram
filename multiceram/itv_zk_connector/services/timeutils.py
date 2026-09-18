# -*- coding: utf-8 -*-
"""Conversions heure locale BioTime ↔ UTC.

BioTime et CVSecurity renvoient des heures « murales », sans fuseau. On garde la
chaîne brute et on la convertit avec zoneinfo :
- heure ambiguë (les horloges reculent) : première occurrence (fold=0) ;
- heure inexistante (les horloges avancent) : décalée vers l'avant.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

LOCAL_FORMATS = ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M:%S')


def parse_local(value):
    """Chaîne BioTime → datetime naïf local (None si vide)."""
    if not value:
        return None
    value = value.strip()
    for fmt in LOCAL_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError("Horodatage BioTime non reconnu : %r" % value)


def local_to_utc(value, tz_name):
    """Chaîne ou datetime naïf local → datetime naïf UTC (convention Odoo)."""
    local = parse_local(value) if isinstance(value, str) else value
    if local is None:
        return None
    return local.replace(tzinfo=ZoneInfo(tz_name), fold=0).astimezone(timezone.utc).replace(tzinfo=None)


def utc_to_local(value, tz_name):
    """Datetime naïf UTC → datetime naïf local."""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tz_name)).replace(tzinfo=None)


def format_local(value):
    """Datetime naïf local → chaîne au format attendu par les filtres BioTime."""
    return value.strftime('%Y-%m-%d %H:%M:%S') if value else None
