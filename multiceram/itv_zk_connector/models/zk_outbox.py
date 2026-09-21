# -*- coding: utf-8 -*-
from odoo import fields, models


class ItvZkOutbox(models.Model):
    _name = 'itv.zk.outbox'
    _inherit = ['itv.audit.mixin']
    _description = "File d'envoi vers BioTime"
    _order = 'id desc'

    backend_id = fields.Many2one('itv.zk.backend', string="Connexion", required=True, ondelete='cascade', index=True)
    operation = fields.Selection([
        ('manuallog', "Pointage manuel"),
        ('schedule', "Planning (jour de repos)"),
        ('holiday', "Jour férié"),
        ('attlog', "Passage UHF (ATTLOG)"),
    ], string="Opération", required=True)
    payload = fields.Json("Contenu", required=True)
    res_model = fields.Char("Modèle d'origine")
    res_id = fields.Many2oneReference("Enregistrement d'origine", model_field='res_model')
    state = fields.Selection(tracking=True, selection=[
        ('pending', "En attente"),
        ('sent', "Envoyé"),
        ('confirmed', "Confirmé"),
        ('error', "Erreur"),
    ], string="État", required=True, default='pending', index=True)
    attempts = fields.Integer("Tentatives")
    biotime_ref = fields.Char("Référence BioTime")
    sent_at = fields.Datetime("Envoyé le")
    last_error = fields.Text("Dernière erreur")
