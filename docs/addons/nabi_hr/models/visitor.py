# -*- coding: utf-8 -*-

from odoo import models,fields, api, _
import requests,json,base64
from odoo.exceptions import UserError
from datetime import datetime, timedelta
import logging
_logger = logging.getLogger(__name__)


class ZkTerminals(models.Model):
    _name = "visitor"
    _description = "Visiteurs"

    name                = fields.Char("Nom / Prénom" , copy=False, required=True)
    accompagne_par      = fields.Text("Accompagné par")
    id_number           = fields.Char("CNIE / Passport/" ,required=True)
    societe             = fields.Char('Société', required=True)
    objet_visite        = fields.Text("Object de visite",required=True)
    service             = fields.Text("service visité",required=True)
    employee_id         = fields.Many2one('hr.employee' ,"Personne accueillante",required=True)

    declaration_entree  = fields.Text("Declaration à l'entrée")
    date_entree         = fields.Datetime("Date d'entrée")
    declaration_sortie  = fields.Text("Declaration à la sortie")
    date_sortie         = fields.Datetime("Date de sortie")
    numero_badge        = fields.Char("Numéro de badge")
    consignes           = fields.Text("Consignes")
    state               = fields.Selection([('n','Nouveau'),('a','Arrivé(e)'),('p','Parti(e)'),('s','A suivre')], "Etat" , default="n")


    def checkin(self):
        for o in self:
            o.date_entree = fields.Datetime.now()
            o.state = "a"
    def checkout(self):
        for o in self:
            o.date_sortie = fields.Datetime.now()
            o.state = "p"



