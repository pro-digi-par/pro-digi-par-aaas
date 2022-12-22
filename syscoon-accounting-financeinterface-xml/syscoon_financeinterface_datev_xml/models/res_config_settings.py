# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models, fields


class syscoonFinanceInterfaceConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    company_export_xml_mode = fields.Selection(
        related='company_id.export_xml_mode',
        readonly=False
    )
    company_export_xml_group_lines = fields.Boolean(
        related='company_id.export_xml_group_lines',
        readonly=False
    )
    company_export_xml_analytic_accounts = fields.Boolean(
        related='company_id.export_xml_analytic_accounts',
        readonly=False
    )
