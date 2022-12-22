#See LICENSE file for full copyright and licensing details.

import math

from odoo import models, api, fields


class AccountTax(models.Model):
    _inherit = 'account.tax'

    datev_discount_account = fields.Many2one('account.account', string='DATEV Discount Account')