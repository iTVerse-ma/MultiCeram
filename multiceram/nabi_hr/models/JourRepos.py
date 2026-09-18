# -*- coding: utf-8 -*-

from odoo import models, fields


class XJourRepos(models.Model):
    """Modèle créé avec Studio dans mc2 (Odoo 18), repris dans le code pour Odoo 19 sans changer de nom."""
    _name = 'x_jour_repos'
    _description = "Validation des HS"
    _rec_name = 'x_name'

    x_name = fields.Char("Nom")
    x_employee_id = fields.Many2one('hr.employee', "Employé", required=True)
    x_date = fields.Date("Date")
    x_jour_repos = fields.Boolean("Jour de repos")
    x_circuit = fields.Datetime("Mise en circuit")
    x_validation_1 = fields.Boolean("Validation 1")
    x_date_1 = fields.Datetime("Date validation 1")
    x_validation_2 = fields.Boolean("Validation 2")
    x_date_2 = fields.Datetime("Date validation 2")
    x_heures = fields.Float("Heures")
    x_hs = fields.Float("HS")
    x_hs_corrige = fields.Float("HS corrigées")
    x_hs_25 = fields.Float("HS 25 %")
    x_hs_50 = fields.Float("HS 50 %")
    x_hs_100 = fields.Float("HS 100 %")
