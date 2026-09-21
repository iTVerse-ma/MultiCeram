# -*- coding: utf-8 -*-
"""Applique le périmètre « organigramme » aux règles natives, marquées noupdate."""
import importlib

from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    hooks = importlib.import_module('odoo.addons.itv_zk_attendance.hooks')
    hooks.apply_hierarchy_rules(api.Environment(cr, SUPERUSER_ID, {}))
