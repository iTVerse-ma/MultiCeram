# -*- coding: utf-8 -*-

from odoo import models,fields, api, _
import requests,json,base64
from odoo.exceptions import UserError
from datetime import datetime, timedelta
import logging
_logger = logging.getLogger(__name__)


class HrEmployee(models.Model):
    _inherit = "hr.employee"


    zk_id = fields.Char("Id Zk")