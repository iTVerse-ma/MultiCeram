# -*- coding: utf-8 -*-
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# Codes renvoyés par BioTime dans le champ « state » des terminaux.
BIOTIME_STATES = {
    '0': "Hors ligne",
    '1': "En ligne",
}

TERMINAL_USAGES = [
    ('t', "Présence"),
    ('p', "Porte (pause)"),
    ('r', "Restaurant"),
    ('m', "Magasin"),
    ('x', "Ignoré"),
    ('unclassified', "À classer"),
]


class ItvZkTerminal(models.Model):
    _name = 'itv.zk.terminal'
    _description = "Terminal BioTime"
    _order = 'backend_id, alias, sn'
    _rec_name = 'alias'

    backend_id = fields.Many2one('itv.zk.backend', string="Connexion", required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='backend_id.company_id', store=True, index=True)
    active = fields.Boolean(default=True)
    biotime_id = fields.Integer("ID BioTime", index=True, copy=False)
    sn = fields.Char("N° de série", required=True, copy=False,
                     help="Numéro de série gravé dans l'appareil, transmis par BioTime. "
                          "Il identifie le terminal : le changer romprait le lien avec ses pointages.")
    alias = fields.Char("Nom", required=True)
    area_name = fields.Char("Zone BioTime")
    biotime_area_id = fields.Integer("ID zone BioTime", readonly=True,
                                     help="Zone du terminal dans BioTime : un employé est envoyé à toutes les "
                                          "pointeuses de ses zones.")
    ip_address = fields.Char("Adresse IP")
    biotime_state = fields.Char("État BioTime (code brut)")
    terminal_tz = fields.Char("Fuseau déclaré (code brut)")
    biotime_state_label = fields.Char(
        "État BioTime", compute='_compute_biotime_labels',
        help="Ce que BioTime sait de l'appareil à la dernière synchronisation.")
    terminal_tz_label = fields.Char(
        "Fuseau déclaré par l'appareil", compute='_compute_biotime_labels',
        help="Fuseau annoncé par la pointeuse elle-même. Beaucoup d'appareils restent sur la valeur "
             "d'usine (UTC+08:00) tant qu'on ne les règle pas dans leur menu.\n"
             "Cette valeur est indicative : les calculs d'Odoo suivent le fuseau de la connexion, "
             "ou le « Fuseau forcé » ci-dessous s'il est renseigné.")
    usage = fields.Selection(TERMINAL_USAGES, string="Usage", required=True, default='unclassified',
                             help="Détermine comment les pointages de ce terminal entrent dans les calculs.")
    direction = fields.Selection(
        [('in', "Entrée"), ('out', "Sortie"), ('none', "Sans sens")],
        string="Sens", required=True, default='none')
    is_uhf_bridge = fields.Boolean("Pont UHF (CVSecurity)",
                                   help="Terminal virtuel qui reçoit les passages des lecteurs UHF de CVSecurity.")
    is_virtual = fields.Boolean("Terminal virtuel")
    timezone_override = fields.Char(
        "Fuseau forcé",
        help="À renseigner si l'horloge de ce terminal ne suit pas le fuseau de la connexion "
             "(ex. décalage d'une heure pendant le Ramadan).")
    last_activity = fields.Datetime("Dernière activité", readonly=True)
    offline_since = fields.Datetime("Hors ligne depuis", readonly=True)

    @api.depends('biotime_state', 'terminal_tz')
    def _compute_biotime_labels(self):
        for terminal in self:
            code = (terminal.biotime_state or '').strip()
            terminal.biotime_state_label = BIOTIME_STATES.get(code) or (_("Inconnu (%s)", code) if code else False)
            terminal.terminal_tz_label = self._format_terminal_tz(terminal.terminal_tz)

    @staticmethod
    def _format_terminal_tz(value):
        """BioTime renvoie un entier : des heures (8) sur les appareils PUSH, des minutes (480) sur d'autres."""
        try:
            number = int(str(value or '').strip())
        except (TypeError, ValueError):
            return value or False
        minutes = number * 60 if -14 <= number <= 14 else number
        sign = '-' if minutes < 0 else '+'
        minutes = abs(minutes)
        return "UTC%s%02d:%02d" % (sign, minutes // 60, minutes % 60)

    _backend_sn_uniq = models.UniqueIndex('(backend_id, sn)', "Ce numéro de série existe déjà pour cette connexion BioTime.")

    @api.constrains('timezone_override')
    def _check_timezone_override(self):
        for terminal in self.filtered('timezone_override'):
            try:
                ZoneInfo(terminal.timezone_override)
            except (ZoneInfoNotFoundError, ValueError):
                raise ValidationError(_("Fuseau horaire inconnu : %s", terminal.timezone_override))

    @api.model
    def _get_or_create_by_sn(self, backend, aliases_by_sn):
        """Rend {n° de série: terminal} ; crée « à classer » les terminaux encore inconnus."""
        serials = [serial for serial in aliases_by_sn if serial]
        if not serials:
            return {}
        terminals = self.with_context(active_test=False).search([('backend_id', '=', backend.id), ('sn', 'in', serials)])
        by_sn = {terminal.sn: terminal for terminal in terminals}
        missing = [serial for serial in serials if serial not in by_sn]
        if missing:
            created = self.create([
                {'backend_id': backend.id, 'sn': serial, 'alias': aliases_by_sn[serial] or serial}
                for serial in missing
            ])
            by_sn.update((terminal.sn, terminal) for terminal in created)
        return by_sn
