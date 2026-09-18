# -*- coding: utf-8 -*-
"""Lien d'activation et QR du courrier remis à l'employé.

Le QR est calculé en Python : wkhtmltopdf ne sait pas récupérer l'image du code-barres
par URL depuis le PDF (ContentNotFoundError).
"""
import base64

from odoo import fields, models

QR_SIZE = 300


class ResUsers(models.Model):
    _inherit = 'res.users'

    itv_signup_url = fields.Char("Lien d'activation", compute='_compute_itv_signup')
    itv_signup_qr = fields.Binary("QR d'activation", compute='_compute_itv_signup')

    def _compute_itv_signup(self):
        report = self.env['ir.actions.report']
        for user in self:
            url = user.partner_id.sudo()._get_signup_url() or ''
            user.itv_signup_url = url
            user.itv_signup_qr = base64.b64encode(
                report.barcode('QR', url, width=QR_SIZE, height=QR_SIZE)) if url else False
