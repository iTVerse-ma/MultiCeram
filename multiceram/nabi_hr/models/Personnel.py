# -*- coding: utf-8 -*-

from odoo import models, fields


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    zk_id = fields.Char("Id Zk")

    # Champs créés avec Studio dans mc2 (Odoo 18), repris dans le code pour Odoo 19 sans changer leur nom.
    x_acc_pin = fields.Char("PIN CVSecurity")
    x_acc_pin2 = fields.Char("PIN CVSecurity 2")
    x_day_hour = fields.Integer("Heures par jour")
    x_heure_supp = fields.Boolean("Heures supplémentaires")
    x_horaire = fields.Selection([('normal', "Normal"), ('poste', "Poste"), ('securite', "Sécurité")], "Horaire")
    x_ignore_uhf = fields.Boolean("Ignorer UHF")
    x_pause = fields.Boolean("Pause")
    x_workedday_week = fields.Integer("Heures par semaine")
