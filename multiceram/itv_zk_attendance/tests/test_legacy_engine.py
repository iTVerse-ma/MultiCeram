# -*- coding: utf-8 -*-
from datetime import date, datetime, timedelta

from odoo.tests.common import BaseCase, tagged

from ..services.legacy_engine import (
    LegacyEmployeeSettings,
    LegacyOvertimeRow,
    LegacyPageError,
    LegacyPunch,
    compute_legacy_page,
    legacy_anomaly_labels,
    round_arrival,
    round_departure,
)

H = timedelta(hours=1)


def at(value):
    return datetime.strptime(value, '%Y-%m-%d %H:%M:%S')


class PunchFactory:

    def __init__(self):
        self.next_id = 1

    def __call__(self, when, usage='t', direction=None, **kwargs):
        punch = LegacyPunch(id=self.next_id, local_time=at(when), usage=usage, direction=direction, **kwargs)
        self.next_id += 1
        return punch


@tagged('post_install', '-at_install', 'itv_zk_attendance')
class TestLegacyRounding(BaseCase):

    def test_arrival_rounds_to_nearest_half_hour_with_bankers_rounding(self):
        cases = {
            '2025-11-03 08:01:00': '08:00', '2025-11-03 08:15:59': '08:00', '2025-11-03 08:16:00': '08:30',
            '2025-11-03 08:44:00': '08:30', '2025-11-03 08:45:00': '09:00', '2025-11-03 23:44:00': '23:30',
        }
        for value, expected in cases.items():
            self.assertEqual(round_arrival(at(value)).strftime('%H:%M'), expected, value)

    def test_arrival_at_23_45_overflows_like_the_original(self):
        with self.assertRaises(ValueError):
            round_arrival(at('2025-11-03 23:45:00'))

    def test_departure_rounding(self):
        cases = {'16:19:59': '16:00', '16:20:00': '16:30', '16:44:00': '16:30', '16:45:00': '17:00', '23:50:00': '00:00'}
        for value, expected in cases.items():
            self.assertEqual(round_departure(at('2025-11-03 ' + value)).strftime('%H:%M'), expected, value)


@tagged('post_install', '-at_install', 'itv_zk_attendance')
class TestLegacyPage(BaseCase):

    def setUp(self):
        super().setUp()
        self.punch = PunchFactory()
        self.normal = LegacyEmployeeSettings(schedule_type='normal')

    def test_plain_day_hours_overtime_and_absence(self):
        # Lundi 03/11/2025, horaire « normal » : 07:58 → 18:10, passage restaurant à 12:30.
        punches = [
            self.punch('2025-11-03 07:58:00', 't', 'in'),
            self.punch('2025-11-03 12:30:00', 'r'),
            self.punch('2025-11-03 18:10:00', 't', 'out'),
        ]
        page = compute_legacy_page(date(2025, 11, 3), date(2025, 11, 3), punches, self.normal)
        day = page.days[0]
        self.assertEqual(day.pause, H)
        self.assertEqual(day.heures, timedelta(hours=9, minutes=10))      # 18:10 − 08:00 − 1 h
        self.assertEqual(day.heures25, timedelta(hours=9))                # 18:00 − 08:00 − 1 h
        self.assertEqual(day.hs, timedelta(minutes=10))                   # 9:10 − (8 h + 1 h)
        self.assertEqual(day.hs25_raw, timedelta())
        self.assertEqual(day.abs25, timedelta())
        self.assertEqual(day.anomalies, ())

    def test_five_minute_duplicates_are_dropped_in_a_chain(self):
        punches = [
            self.punch('2025-11-03 08:00:00', 't', 'in'),
            self.punch('2025-11-03 08:04:00', 't', 'in'),   # doublon du précédent
            self.punch('2025-11-03 08:08:00', 't', 'in'),   # doublon en chaîne (≤ 5 min du 08:04)
            self.punch('2025-11-03 17:00:00', 't', 'out'),
        ]
        page = compute_legacy_page(date(2025, 11, 3), date(2025, 11, 3), punches, LegacyEmployeeSettings())
        self.assertEqual(page.days[0].punch_count, 2)
        self.assertEqual(page.days[0].anomalies, ())

    def test_odd_presence_zeroes_hours_and_counts_full_absence(self):
        punches = [self.punch('2025-11-03 08:00:00', 't', 'in'), self.punch('2025-11-03 12:00:00', 't', None), self.punch('2025-11-03 17:00:00', 't', 'out')]
        day = compute_legacy_page(date(2025, 11, 3), date(2025, 11, 3), punches, LegacyEmployeeSettings()).days[0]
        self.assertEqual(day.anomalies, ('t',))
        self.assertEqual((day.heures, day.heures25, day.abs25), (timedelta(), timedelta(), 8 * H))

    def test_night_shift_carries_next_day_leading_exits(self):
        punches = [self.punch('2025-11-03 22:02:00', 't', 'in'), self.punch('2025-11-04 06:03:00', 't', 'out')]
        page = compute_legacy_page(date(2025, 11, 3), date(2025, 11, 4), punches, LegacyEmployeeSettings(schedule_type='poste'))
        monday, tuesday = page.days
        self.assertEqual((monday.carried_from_next_day, monday.clean_count), (1, 2))
        self.assertEqual(monday.heures, timedelta(hours=8, minutes=3))    # 06:03 − 22:00
        self.assertEqual(tuesday.punch_count, 0)

    def test_carry_on_the_last_day_crashes_like_the_original(self):
        punches = [self.punch('2025-11-03 06:00:00', 't', 'out'), self.punch('2025-11-03 22:00:00', 't', 'in')]
        with self.assertRaises(LegacyPageError) as error:
            compute_legacy_page(date(2025, 11, 3), date(2025, 11, 3), punches, LegacyEmployeeSettings())
        self.assertEqual(error.exception.kind, LegacyPageError.CARRY_LAST_DAY)

    def test_restaurant_within_fifteen_minutes_of_arrival_cancels_the_pause(self):
        punches = [
            self.punch('2025-11-03 08:00:00', 't', 'in'),
            self.punch('2025-11-03 08:10:00', 'r'),
            self.punch('2025-11-03 17:00:00', 't', 'out'),
        ]
        day = compute_legacy_page(date(2025, 11, 3), date(2025, 11, 3), punches, LegacyEmployeeSettings()).days[0]
        self.assertEqual(day.pause, timedelta())

    def test_two_restaurant_punches_crash_like_the_original(self):
        punches = [
            self.punch('2025-11-03 08:00:00', 't', 'in'),
            self.punch('2025-11-03 12:00:00', 'r'),
            self.punch('2025-11-03 12:40:00', 'r'),
            self.punch('2025-11-03 17:00:00', 't', 'out'),
        ]
        with self.assertRaises(LegacyPageError) as error:
            compute_legacy_page(date(2025, 11, 3), date(2025, 11, 3), punches, LegacyEmployeeSettings())
        self.assertEqual(error.exception.kind, LegacyPageError.MULTIPLE_RESTAURANT)

    def test_saturday_norm_for_44_hour_normal_staff(self):
        settings = LegacyEmployeeSettings(schedule_type='normal', week_hours=44)
        punches = [self.punch('2025-11-08 08:00:00', 't', 'in'), self.punch('2025-11-08 13:00:00', 't', 'out')]
        day = compute_legacy_page(date(2025, 11, 8), date(2025, 11, 8), punches, settings).days[0]
        self.assertEqual((day.pause, day.heures, day.hs), (timedelta(), 5 * H, H))

    def test_sunday_hours_are_reported_at_fifty_percent_for_normal_staff(self):
        punches = [self.punch('2025-11-09 08:00:00', 't', 'in'), self.punch('2025-11-09 12:00:00', 't', 'out')]
        day = compute_legacy_page(date(2025, 11, 9), date(2025, 11, 9), punches, self.normal).days[0]
        self.assertEqual(day.hs50, 4 * H)

    def test_totals_include_negative_hs25_and_manual_overtime(self):
        # Norme 8,1 h (8 h 06) : présence 8 h 10 au-dessus de la norme, mais départ arrondi à 16:00
        # → HS 25 % brute de −6 min, gardée négative dans le total comme sur la page d'origine.
        punches = [self.punch('2025-11-03 08:00:00', 't', 'in'), self.punch('2025-11-03 16:10:00', 't', 'out')]
        rows = {date(2025, 11, 3): [LegacyOvertimeRow(hs_corrige=2.0, hs_25=1.5, hs_50=0.5)]}
        settings = LegacyEmployeeSettings(day_hours=8.1)
        page = compute_legacy_page(date(2025, 11, 3), date(2025, 11, 3), punches, settings, overtime_rows=rows)
        self.assertEqual(page.days[0].hs, timedelta(minutes=4))
        self.assertEqual(page.days[0].hs25_raw, timedelta(minutes=-6))
        self.assertEqual(page.days[0].hs25, timedelta())
        self.assertEqual(page.days[0].abs25, timedelta(minutes=6))
        self.assertEqual(page.totals.hs_declare, 2 * H)
        self.assertEqual(page.totals.hs25, timedelta(hours=1, minutes=24))
        self.assertEqual(page.totals.hs50, timedelta(minutes=30))

    def test_two_overtime_rows_on_one_day_crash_like_the_original(self):
        rows = {date(2025, 11, 3): [LegacyOvertimeRow(), LegacyOvertimeRow()]}
        with self.assertRaises(LegacyPageError) as error:
            compute_legacy_page(date(2025, 11, 3), date(2025, 11, 3), [], LegacyEmployeeSettings(), overtime_rows=rows)
        self.assertEqual(error.exception.kind, LegacyPageError.MULTIPLE_OVERTIME_ROWS)

    def test_first_display_crash_wins_over_duplicate_removal(self):
        # Passages restaurant à 3 min d'écart : le 2e est un doublon « 5 min », mais le 1er affichage
        # plantait avant que ce marquage soit validé ; la page plantait donc à chaque rechargement.
        punches = [
            self.punch('2025-11-03 08:00:00', 't', 'in'),
            self.punch('2025-11-03 12:00:00', 'r'),
            self.punch('2025-11-03 12:03:00', 'r'),
            self.punch('2025-11-03 17:00:00', 't', 'out'),
        ]
        with self.assertRaises(LegacyPageError) as error:
            compute_legacy_page(date(2025, 11, 3), date(2025, 11, 3), punches, LegacyEmployeeSettings())
        self.assertEqual(error.exception.kind, LegacyPageError.MULTIPLE_RESTAURANT)


@tagged('post_install', '-at_install', 'itv_zk_attendance')
class TestLegacyAnomalyLabels(BaseCase):

    def setUp(self):
        super().setUp()
        self.punch = PunchFactory()

    def test_labels(self):
        self.assertEqual(legacy_anomaly_labels([]), ("Absent",))
        same_minute = [self.punch('2025-11-03 08:00:10', 't'), self.punch('2025-11-03 08:00:50', 't'), self.punch('2025-11-03 17:00:00', 't')]
        self.assertEqual(legacy_anomaly_labels(same_minute), ("Aucune anomalie",))
        only_doors = [self.punch('2025-11-03 10:00:00', 'p')]
        self.assertEqual(legacy_anomaly_labels(only_doors), ("Détecté présent", "Porte impaire"))
        manual_odd = [self.punch('2025-11-03 08:00:00', None)]
        self.assertEqual(legacy_anomaly_labels(manual_odd), ("Pointage impaire",))
