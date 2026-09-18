# -*- coding: utf-8 -*-
"""Le PIN pointeuse maison est fusionné dans le « Code PIN » natif avant la suppression de sa colonne."""


def migrate(cr, version):
    cr.execute("""
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'hr_employee' AND column_name = 'itv_biotime_pin'
    """)
    if not cr.fetchone():
        return
    cr.execute("""
        UPDATE hr_employee
           SET pin = itv_biotime_pin
         WHERE itv_biotime_pin ~ '^[0-9]+$'
           AND pin IS DISTINCT FROM itv_biotime_pin
    """)
