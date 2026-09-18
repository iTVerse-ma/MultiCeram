# -*- coding: utf-8 -*-
"""Les tâches planifiées passent en « noupdate » : le mode de synchronisation choisi survit aux mises à jour.

Odoo ne bascule pas ce drapeau sur des enregistrements déjà créés : on le pose ici.
"""


def migrate(cr, version):
    cr.execute("""
        UPDATE ir_model_data
           SET noupdate = TRUE
         WHERE module = 'itv_zk_connector' AND model = 'ir.cron'
    """)
