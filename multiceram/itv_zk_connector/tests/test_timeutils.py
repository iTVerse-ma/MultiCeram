# -*- coding: utf-8 -*-
from datetime import datetime

from odoo.tests.common import BaseCase, tagged

from ..services.timeutils import local_to_utc, parse_local, utc_to_local

TZ = 'Africa/Casablanca'


@tagged('post_install', '-at_install', 'itv_zk')
class TestTimeUtils(BaseCase):

    def test_standard_time_is_utc_plus_one(self):
        self.assertEqual(local_to_utc('2026-01-10 08:00:00', TZ), datetime(2026, 1, 10, 7, 0))

    def test_ramadan_period_is_utc(self):
        self.assertEqual(local_to_utc('2026-03-01 08:00:00', TZ), datetime(2026, 3, 1, 8, 0))

    def test_ambiguous_hour_takes_the_first_occurrence(self):
        # 15/02/2026 : à 03:00 (UTC+1) les horloges reculent à 02:00 (UTC+0) ; 02:30 existe deux fois.
        self.assertEqual(local_to_utc('2026-02-15 02:30:00', TZ), datetime(2026, 2, 15, 1, 30))

    def test_skipped_hour_is_moved_forward(self):
        # 22/03/2026 : à 02:00 (UTC+0) les horloges avancent à 03:00 (UTC+1) ; 02:30 n'existe pas.
        utc = local_to_utc('2026-03-22 02:30:00', TZ)
        self.assertEqual(utc, datetime(2026, 3, 22, 2, 30))
        self.assertEqual(utc_to_local(utc, TZ), datetime(2026, 3, 22, 3, 30))

    def test_round_trip_outside_transitions(self):
        for value in ('2026-09-10 22:01:05', '2026-12-31 23:59:59'):
            self.assertEqual(utc_to_local(local_to_utc(value, TZ), TZ), parse_local(value))

    def test_accepted_formats_and_empty_values(self):
        self.assertEqual(parse_local('2026-09-10 06:02'), datetime(2026, 9, 10, 6, 2))
        self.assertIsNone(local_to_utc('', TZ))
        with self.assertRaises(ValueError):
            parse_local('10/09/2026')
