# -*- coding: utf-8 -*-
"""Fusion des deux groupes de responsables en un seul.

Le niveau de validation vient désormais de l'organigramme : un seul droit « Responsable »
suffit. Les utilisateurs de l'ancien groupe N2 le reçoivent avant sa suppression.
"""


def migrate(cr, version):
    cr.execute("""
        INSERT INTO res_groups_users_rel (gid, uid)
        SELECT n1.res_id, rel.uid
          FROM res_groups_users_rel rel
          JOIN ir_model_data n2 ON n2.model = 'res.groups' AND n2.module = 'itv_zk_attendance'
                               AND n2.name = 'group_itv_overtime_validation_2' AND n2.res_id = rel.gid
          JOIN ir_model_data n1 ON n1.model = 'res.groups' AND n1.module = 'itv_zk_attendance'
                               AND n1.name = 'group_itv_overtime_validation_1'
        ON CONFLICT DO NOTHING
    """)
