# -*- coding: utf-8 -*-
"""Libellé français du groupe aligné sur le nouveau nom.

Odoo conserve les traductions existantes quand un fichier de données renomme un
enregistrement : la fiche affichait encore « Responsable N1 » en français.
"""


def migrate(cr, version):
    cr.execute("""
        UPDATE res_groups g
           SET name = jsonb_set(g.name, '{fr_FR}', g.name -> 'en_US')
          FROM ir_model_data d
         WHERE d.model = 'res.groups' AND d.res_id = g.id
           AND d.module = 'itv_zk_attendance' AND d.name = 'group_itv_overtime_validation_1'
           AND g.name ->> 'fr_FR' IS DISTINCT FROM g.name ->> 'en_US'
    """)
