# -*- coding: utf-8 -*-
"""Calcul historique nabi_hr, reproduit à l'identique, bugs compris.

Sources reproduites :
- nabi_hr/controllers/Attendance.py, `portal_get_punch_stacked` (L182-509) : page
  « Pointages / employé », un employé sur une plage de dates ;
- vue QWeb mc2 n° 2701 : page « Anomalies par employé », un jour.

Aucune dépendance à l'ORM : les entrées sont des objets simples, ce qui permet de
comparer le résultat à la référence calculée par le code d'origine (tools/migration_nabi).

Deux comportements de la page d'origine sont conservés volontairement :
- elle marquait les doublons « 5 min » pendant l'affichage : les chiffres retenus sont
  ceux du rechargement suivant, qui excluait ces pointages ;
- elle plantait dans quatre cas : LegacyPageError en indique la cause.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

ZERO = timedelta()
ONE_HOUR = timedelta(hours=1)
DUPLICATE_WINDOW = timedelta(minutes=5)
RESTAURANT_MARGIN = timedelta(minutes=15)
PRESENCE_USAGES = ('t', None)  # terminal de présence, ou pointage sans terminal (manuel)


class LegacyPageError(Exception):
    """La page d'origine plantait sur cette plage ; `kind` en donne la cause."""

    ROUND_OVERFLOW = 'round_overflow'                  # arrivée ≥ 23:45 → heure 24 (ValueError)
    CARRY_LAST_DAY = 'carry_last_day'                  # dernier jour « sortie … entrée » (IndexError)
    MULTIPLE_RESTAURANT = 'multiple_restaurant'        # plusieurs passages restaurant (singleton)
    MULTIPLE_OVERTIME_ROWS = 'multiple_overtime_rows'  # plusieurs lignes x_jour_repos le même jour (singleton)

    def __init__(self, kind, day):
        super().__init__("%s (%s)" % (kind, day))
        self.kind = kind
        self.day = day


@dataclass(frozen=True)
class LegacyPunch:
    id: int
    local_time: datetime                 # heure murale, telle qu'envoyée par BioTime
    usage: str | None = 't'              # t, p, r… ; None = sans terminal
    direction: str | None = None         # 'in', 'out' ou None
    duplicate: bool = False
    to_delete: bool = False
    date_override: date | None = None
    uhf_bridge: bool = False


@dataclass(frozen=True)
class LegacyEmployeeSettings:
    schedule_type: str | None = None     # 'normal', 'poste', 'securite' ou None
    day_hours: float | None = None       # None → 8 h
    week_hours: int | None = None        # 44 ou 48
    auto_pause: bool = False
    ignore_uhf: bool = False


@dataclass(frozen=True)
class LegacyHoliday:
    date_from: datetime                  # UTC naïf, comme en base
    date_to: datetime


@dataclass(frozen=True)
class LegacyLeave:
    id: int
    date_from: date
    date_to: date


@dataclass(frozen=True)
class LegacyOvertimeRow:
    hs_corrige: float = 0.0
    hs_25: float = 0.0
    hs_50: float = 0.0
    hs_100: float = 0.0


@dataclass
class LegacyTotals:
    normal: timedelta = ZERO            # H.Prés
    normal2: timedelta = ZERO           # H.Nor
    pause: timedelta = ZERO
    absence: timedelta = ZERO
    hs: timedelta = ZERO
    hs_corrige: timedelta = ZERO
    hs_declare: timedelta = ZERO
    hs25: timedelta = ZERO              # HS 25 % brutes (négatives comprises) + saisie manuelle
    hs50: timedelta = ZERO              # saisie manuelle seulement
    hs100: timedelta = ZERO
    days: int = 0
    worked_days: int = 0
    absence_days: int = 0


@dataclass
class LegacyDay:
    day: date
    punch_count: int
    clean_count: int
    carried_from_next_day: int
    first_punch: datetime | None
    last_punch: datetime | None
    pause: timedelta
    heures: timedelta
    heures25: timedelta
    hs: timedelta
    hs25_raw: timedelta
    hs25: timedelta
    hs50: timedelta
    abs25: timedelta
    anomalies: tuple
    door_anomaly: bool
    detected_present: bool
    holiday: bool
    leave_ids: tuple
    has_overtime_row: bool
    overtime_row: 'LegacyOvertimeRow | None' = None
    first_punch_id: int | None = None
    last_punch_id: int | None = None


@dataclass
class LegacyPage:
    days: list = field(default_factory=list)
    totals: LegacyTotals = field(default_factory=LegacyTotals)


def round_arrival(value):
    """roundTo30(mode='proche') : demi-heure la plus proche, arrondi bancaire de Python.

    :15 → :00 et :45 → heure suivante ; au-delà de 23:44 l'heure vaut 24 (ValueError).
    """
    rounded = round((value.hour * 60 + value.minute) / 30) * 30
    return value.replace(hour=rounded // 60, minute=rounded % 60, second=0, microsecond=0)


def round_departure(value):
    """roundTo20(mode='proche') : :00-:19 → :00, :20-:44 → :30, :45-:59 → heure suivante."""
    if value.minute <= 19:
        return value.replace(minute=0, second=0, microsecond=0)
    if value.minute <= 44:
        return value.replace(minute=30, second=0, microsecond=0)
    return (value + ONE_HOUR).replace(minute=0, second=0, microsecond=0)


def _hours(value):
    return timedelta(hours=value or 0)


def _order(punch):
    return punch.local_time, punch.id


def compute_legacy_page(start, end, punches, settings, holidays=(), leaves=(), overtime_rows=None):
    """Page « Pointages / employé » pour un employé sur [start, end] (dates locales incluses).

    `punches` : pointages de l'employé, doublons et écartés compris (ils sont filtrés ici).
    `overtime_rows` : {jour: [LegacyOvertimeRow, …]} issus de x_jour_repos.

    Rend les chiffres du rechargement (doublons « 5 min » marqués au 1er affichage exclus), sauf si
    le 1er affichage plantait : LegacyPageError, comme chaque rechargement de la page d'origine.
    """
    overtime_rows = overtime_rows or {}
    selected = [
        punch for punch in punches
        if not punch.duplicate and not punch.to_delete and start <= punch.local_time.date() <= end
        and not (settings.ignore_uhf and punch.uhf_bridge)
    ]

    # Premier affichage : doublons « 5 min » par (usage, jour), en chaîne.
    flagged, seen = set(), {}
    for punch in sorted(selected, key=_order):
        key = (punch.usage, punch.local_time.date())
        if key in seen and punch.local_time - seen[key] <= DUPLICATE_WINDOW:
            flagged.add(punch.id)
        seen[key] = punch.local_time
    if flagged:
        # 1er affichage, doublons encore présents : s'il plantait, la transaction était annulée avec
        # le marquage des doublons, et chaque rechargement plantait de la même façon.
        _render_page(start, end, sorted(selected, key=_order), settings, holidays, leaves, overtime_rows)
    visible = sorted((punch for punch in selected if punch.id not in flagged), key=_order)
    return _render_page(start, end, visible, settings, holidays, leaves, overtime_rows)


def _render_page(start, end, visible, settings, holidays, leaves, overtime_rows):
    """Un affichage de la page d'origine, sur les pointages donnés."""
    days = [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
    by_day = {day: [] for day in days}
    for punch in visible:
        applied = punch.date_override or punch.local_time.date()
        if applied in by_day:
            by_day[applied].append(punch)

    window_start = datetime.combine(start, time.min)
    window_end = datetime.combine(end, time.max)
    holidays = [
        holiday for holiday in holidays
        if window_start <= holiday.date_from <= window_end or window_start <= holiday.date_to <= window_end
    ]

    page = LegacyPage()
    totals = page.totals
    totals.days = len(days)
    normal = settings.schedule_type == 'normal'
    carried_ids = set()
    for index, day in enumerate(days):
        data = [punch for punch in by_day[day] if punch.id not in carried_ids]
        carried_ids = set()
        next_day = by_day[days[index + 1]] if index + 1 < len(days) else None

        # Précédence Python d'origine : (lendemain non vide et une seule entrée) OU (sortie … entrée).
        single_in = len(data) == 1 and data[0].direction == 'in'
        out_then_in = bool(data) and data[0].direction == 'out' and data[-1].direction == 'in'
        carried = []
        if (next_day and single_in) or out_then_in:
            if next_day is None:
                raise LegacyPageError(LegacyPageError.CARRY_LAST_DAY, day)
            for candidate in next_day:
                if candidate.direction != 'out':
                    break
                carried.append(candidate)
        carried_ids = {punch.id for punch in carried}
        data = data + [punch for punch in carried if punch not in data]

        if data and data[0].direction == 'out':
            clean = data[1:]
        elif data and data[-1].direction == 'in':
            clean = data[:-1]
        else:
            clean = data
        doors = [punch for punch in clean[1:-1] if punch.usage == 'p']
        presence = [punch for punch in clean if punch.usage in PRESENCE_USAGES]
        restaurant = [punch for punch in clean if punch.usage == 'r']
        if data:
            totals.worked_days += 1

        presence_anomaly = len(presence) % 2 > 0
        door_anomaly = len(doors) % 2 > 0
        detected_present = not presence and bool(data)
        anomalies = []
        if presence_anomaly:
            anomalies.append('t')
        if door_anomaly:
            anomalies.append('p')
        if detected_present:
            anomalies.append('p')

        norm = timedelta(hours=settings.day_hours or 8)
        pause = ZERO
        if not presence_anomaly and presence:
            if settings.auto_pause or doors:
                pause = ONE_HOUR
            elif restaurant:
                if len(restaurant) > 1:
                    raise LegacyPageError(LegacyPageError.MULTIPLE_RESTAURANT, day)
                meal, first, last = restaurant[0].local_time, presence[0].local_time, presence[-1].local_time
                if first < meal < last:
                    pause = ONE_HOUR
                if ZERO < meal - first < RESTAURANT_MARGIN:
                    pause = ZERO
                if ZERO < last - meal < RESTAURANT_MARGIN:
                    pause = ZERO

        if normal and day.weekday() == 5:
            norm = timedelta(hours=4) if settings.week_hours == 44 else timedelta(hours=8)
            pause = ZERO
        if normal and day.weekday() == 6:
            norm = timedelta(hours=8)
            pause = ZERO

        heures = heures25 = ZERO
        if not presence_anomaly and clean:
            try:
                arrival = round_arrival(clean[0].local_time)
            except ValueError:
                raise LegacyPageError(LegacyPageError.ROUND_OVERFLOW, day)
            last = clean[-1].local_time
            heures = last.replace(second=0) - arrival
            heures25 = round_departure(last) - arrival

        if normal and heures25 >= timedelta(hours=5):
            heures -= pause
            heures25 -= pause
        elif normal:
            pause = ZERO

        threshold = norm + pause
        hs = heures - threshold if heures > threshold else ZERO
        hs25_raw = heures25 - threshold if heures > threshold else ZERO
        abs25 = norm - heures25 if norm > heures25 else ZERO

        rows = overtime_rows.get(day) or ()
        if len(rows) > 1:
            raise LegacyPageError(LegacyPageError.MULTIPLE_OVERTIME_ROWS, day)
        row = rows[0] if rows else LegacyOvertimeRow()

        totals.normal += heures
        totals.normal2 += heures25
        totals.pause += pause
        totals.absence += abs25
        totals.hs += hs
        totals.hs25 += hs25_raw + _hours(row.hs_25)
        totals.hs_corrige += hs25_raw if hs25_raw > ZERO else ZERO
        totals.hs_declare += _hours(row.hs_corrige)
        totals.hs50 += _hours(row.hs_50)
        totals.hs100 += _hours(row.hs_100)
        if not data:
            totals.absence_days += 1

        page.days.append(LegacyDay(
            day=day,
            punch_count=len(data),
            clean_count=len(clean),
            carried_from_next_day=len(carried),
            first_punch=clean[0].local_time if clean else None,
            last_punch=clean[-1].local_time if clean else None,
            pause=pause,
            heures=heures,
            heures25=heures25,
            hs=hs,
            hs25_raw=hs25_raw,
            hs25=hs25_raw if hs25_raw > ZERO else ZERO,
            hs50=heures25 if heures25 > ZERO and normal and day.weekday() == 6 else ZERO,
            abs25=abs25,
            anomalies=tuple(anomalies),
            door_anomaly=door_anomaly,
            detected_present=detected_present,
            holiday=any(h.date_from.date() <= day <= h.date_to.date() for h in holidays),
            leave_ids=tuple(leave.id for leave in leaves if leave.date_from <= day <= leave.date_to),
            has_overtime_row=bool(rows),
            overtime_row=rows[0] if rows else None,
            first_punch_id=clean[0].id if clean else None,
            last_punch_id=clean[-1].id if clean else None,
        ))
    return page


def legacy_anomaly_labels(day_punches):
    """Libellés de la page « Anomalies par employé » (vue 2701) pour un employé et un jour.

    `day_punches` : tous les pointages du jour, doublons et écartés compris ; les heures
    identiques à la minute ne comptent qu'une fois.
    """
    def distinct_minutes(items):
        return {punch.local_time.strftime('%H:%M') for punch in items}

    presence = distinct_minutes(p for p in day_punches if p.usage in PRESENCE_USAGES)
    restaurant = distinct_minutes(p for p in day_punches if p.usage == 'r')
    doors = distinct_minutes(p for p in day_punches if p.usage == 'p')
    labels = []
    if not day_punches:
        labels.append("Absent")
    if len(presence) % 2 > 0:
        labels.append("Pointage impaire")
    if not presence and (restaurant or doors):
        labels.append("Détecté présent")
    if len(doors) % 2 > 0:
        labels.append("Porte impaire")
    return tuple(labels) or ("Aucune anomalie",)
