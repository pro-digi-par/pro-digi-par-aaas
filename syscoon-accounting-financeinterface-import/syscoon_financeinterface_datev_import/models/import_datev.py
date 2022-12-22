#See LICENSE file for full copyright and licensing details.

from odoo import fields, models, api, _
from odoo.exceptions import UserError

import base64
import csv
import locale
import time
from datetime import datetime
from io import StringIO

ACCOUNT_TYPES = ['asset_receivable',
                 'asset_cash',
                 'asset_current',
                 'asset_non_current',
                 'asset_prepayments',
                 'asset_fixed',
                 'liability_payable',
                 'liability_credit_card',
                 'liability_current',
                 'liability_non_current',
                 'equity',
                 'equity_unaffected',
                 'off_balance',
                 ]

COST_ACCOUNT_TYPES = ['income',
                      'income_other',
                      'expense',
                      'expense_depreciation',
                      'expense_direct_cost',
                      ] 

class ImportDatev(models.Model):
    """
    The class syscoon.datev.import is for the import of DATEV Buchungsstapel (account.moves)
    """
    _name = 'syscoon.datev.import'
    _order = 'name desc'
    _description = 'DATEV ASCII-Import'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char('Name', readonly=True, default=lambda self: self.env['ir.sequence'].get('syscoon.datev.import.sequence') or '-')
    description = fields.Char('Description', required=True)
    template_id = fields.Many2one('syscoon.datev.import.config', string='Import Template')
    journal_id = fields.Many2one('account.journal', 'Journal', required=True)
    one_move = fields.Boolean('In one move?')
    start_date = fields.Date('Start Date', required=True, default=fields.Date.today())
    end_date = fields.Date('End Date', required=True, default=fields.Date.today())
    log_line = fields.One2many('syscoon.datev.import.log', 'parent_id', 'Log')
    account_move_ids = fields.One2many('account.move', 'syscoon_datev_import_id', 'Account Moves')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('error', 'Error'),
        ('imported', 'Imported'),
        ('booked', 'Booked')],
        'Status', index=True, readonly=True, default='draft', tracking=True)

    def start_import(self):
        """Initial function for manage the import of DATEV-moves"""
        #if self.account_move_ids:
        #    self.reset_import()
        self.env['syscoon.datev.import.log'].create({
            'parent_id': self.id,
            'name': _("Import started"),
            'state': 'info',
        })
        moves = False
        log_error = False
        file = self.get_attachment()
        if self.get_import_config()['remove_datev_header']:
            file = self.remove_datev_header(file)
        import_list = self.convert_lines(file)
        logs = self.check_can_created(import_list)
        if logs:
            for log in logs:
                if log['state'] == 'error':
                    log_error = True
                self.env['syscoon.datev.import.log'].create({
                    'parent_id': log['parent_id'],
                    'line': log['line'],
                    'name': log['name'],
                    'state': log['state'],
                })
            if log_error:
                self.write({'state': 'error'})
        if not log_error:
            moves = self.create_values(import_list)
        if moves:
            self.create_moves(moves)
            self.write({'state': 'imported'})
            if self.template_id.auto_reconcile or self.template_id.post_moves:
                self.confirm_moves()
            if self.template_id.auto_reconcile:
                if not self.template_id.discount_account_income:
                    self.env['syscoon.datev.import.log'].create({
                        'parent_id': self.id,
                        'name': _('Income Discount Account not selected in Template!'),
                        'state': 'error',
                    })
                    self.write({'state': 'error'})
                elif not self.template_id.discount_account_expenses:
                    self.env['syscoon.datev.import.log'].create({
                        'parent_id': self.id,
                        'name': _('Expense Discount Account not selected in Template!'),
                        'state': 'error',
                    })
                    self.write({'state': 'error'})
                else:
                    self.reconcile_moves()
        self.env['syscoon.datev.import.log'].create({
            'parent_id': self.id,
            'name': _('Import done'),
            'state': 'info',
        })

    def reset_import(self):
        for move in self.account_move_ids:
            move.line_ids.remove_move_reconcile()
        if self.account_move_ids:
            self.account_move_ids.unlink()
        if self.log_line:
            self.log_line.unlink()
        self.write({'state': 'draft'})

    def confirm_moves(self):
        if self.state == 'imported':
            if self.account_move_ids:
                self.account_move_ids.post()
                self.write({'state': 'booked'})
            self.env['syscoon.datev.import.log'].create({
                'parent_id': self.id,
                'name': _('Moves confirmed'),
                'state': 'info',
            })

    def reconcile_moves(self):
        for move in self.account_move_ids:
            reconcile_lines = []
            opposite_move = False
            if move.ref:
                for l in move.line_ids:
                    if l.account_id.account_type in ['liability_payable', 'asset_receivable']:
                        reconcile_lines.append(l.id)
                        opposite_move = self.env['account.move'].search([('datev_ref', '=', move.ref)])
                if opposite_move:
                    for ol in opposite_move.line_ids:
                        if ol.account_id.account_type in ['liability_payable', 'asset_receivable']:
                            if ol.id not in reconcile_lines:
                                reconcile_lines.append(ol.id)
                if len(reconcile_lines) > 1:
                    amount = 0.0
                    move_lines = self.env['account.move.line'].browse(reconcile_lines)
                    for line in move_lines:
                        if line.reconciled:
                            reconciled = True
                        else:
                            reconciled = False
                    if not reconciled:
                        is_reconciled = move_lines.reconcile()
                    self.env['syscoon.datev.import.log'].create({
                        'parent_id': self.id,
                        'name': _('Move %s reconciled' % move.ref),
                        'state': 'info',
                    })
                if len(reconcile_lines) == 1:
                        self.env['syscoon.datev.import.log'].create({
                        'parent_id': self.id,
                        'name': _('Move %s not reconciled' % move.ref),
                        'state': 'warning',
                    })

    def get_attachment(self):
        attachment = self.env['ir.attachment'].search([
            ('res_model', '=', 'syscoon.datev.import'),
            ('res_id', '=', self.id),
        ])
        if not attachment:
            raise UserError(_('No Import File uploaded, please upload one!'))
        if len(attachment) == 1:
            file = base64.decodebytes(attachment.datas)
            file = file.decode(self.get_import_config()['encoding'])
            return file
        else:
            raise UserError(_('There is more than one file attached to this record. Please make sure that there is only one attached CSV-file.'))

    def get_import_config(self):
        if not self.template_id:
            raise UserError(_('There is no config for this company!'))
        config = {
            'delimiter': str(self.template_id.delimiter),
            'encoding': self.template_id.encoding,
            'quotechar': str(self.template_id.quotechar),
            'headerrow': self.template_id.headerrow,
            'remove_datev_header': self.template_id.remove_datev_header,
            'journal_id': self.journal_id.id,
            'company_id': self.env.company.id,
            'company_currency_id': self.env.company.currency_id.id,
            'discount_account_income': self.template_id.discount_account_income,
            'discount_account_expenses': self.template_id.discount_account_expenses,
            'date': self.start_date,
            'ref': self.template_id.ref,
            'post': self.template_id.post_moves,
            'auto_reconcile': self.template_id.auto_reconcile,
            'payment_difference_handling': self.template_id.payment_difference_handling,
        }
        locale.setlocale(locale.LC_ALL, self.template_id.locale)
        return config

    def get_import_struct(self):
        struct = {}
        for row in self.template_id.import_config_row_ids:
            struct[row.name] = {
                'type': row.assignment_type,
                'field_type': row.assignment_type.field_type,
                'object': row.assignment_type.object,
                'field': row.assignment_type.field,
                'domain': row.assignment_type.domain,
                'default': row.assignment_type.default,
                'account_move_field': row.assignment_type.account_move_field,
                'account_move_line_field': row.assignment_type.account_move_line_field,
                'padding': row.assignment_type.padding,
                'date_format': row.assignment_type.date_format,
                'decimal_sign': row.assignment_type.decimal_sign,
                'skip_at': row.assignment_type.skip_at,
                'required': row.required,
                'skip': row.skip,
                'import_value': False,
            }
        return struct

    def remove_datev_header(self, file):
        file = file[file.index('\n')+1:]
        return file

    def convert_lines(self, file):
        config = self.get_import_config()
        reader = csv.DictReader(
            StringIO(file),
            delimiter=config['delimiter'],
            quotechar=config['quotechar']
        )
        pre_import_list = []
        for row in reader:
            pre_import_list.append(dict(row))
        import_list = []
        for row in pre_import_list:
            struct = self.get_import_struct()
            new_row = {}
            for key, value in row.items():
                if key in struct:
                    struct_values = struct[key]
                    struct_values['import_value'] = value
                    new_row[key] = struct_values
            import_list.append(new_row)
        return import_list

    def check_can_created(self, list):
        logs = []
        count = 1
        for dict in list:
            logs += self.check_required_fields(dict, count)
            count += 1
        count = 1
        for dict in list:
            logs += self.check_values(dict, count)
            count += 1
        return logs

    def check_required_fields(self, dict, count):
        logs = []
        required = ['amount', 'move_sign', 'account', 'counteraccount', 'move_date', 'move_name']
        template_required = self.template_id.import_config_row_ids.search([('required', '=', True)])
        existing = []
        for r in template_required:
            if r.assignment_type.type not in required:
                required.append(r.assignment_type.type)
        for k, v in dict.items():
            if v['type'].type in required and v['import_value']:
                required.remove(v['type'].type)
        if required:
            for r in required:
                field = {key: value for key, value in self.env['syscoon.datev.import.assignment']._fields['type']._description_selection(self.env)}[r]
                logs.append({
                    'parent_id': self.id,
                    'line': count,
                    'name': _('Missing Required Field %s.' % field),
                    'state': 'error'
                })
        return logs

    def check_values(self, dict, count):
        logs = []
        for k, v in dict.items():
            if v['field_type'] == 'decimal':
                try:
                    self.convert_to_float(v['import_value'])
                except:
                    logs.append({
                        'parent_id': self.id,
                        'line': count,
                        'name': _('%s cant be converted.' % k),
                        'state': 'error'
                    })
            if v['type'].type == 'move_sign':
                try:
                    self.check_move_sign(v['import_value'])
                except:
                    logs.append({
                        'parent_id': self.id,
                        'line': count,
                        'name': _('%s does not exist. It must be S or H.' % k),
                        'state': 'error'
                    })
            if v['type'].object and v['import_value']:
                try:
                    self.get_object(v['type'].object, v['type'].field, v['import_value'], v['padding'])
                except:
                    logs.append({
                        'parent_id': self.id,
                        'line': count,
                        'name': _('%s does not exist. Please Check.' % k),
                        'state': 'error'
                    })
            if v['type'].type == 'account':
                partner = self.env['res.partner']
                partner_check = False
                account_id = self.get_object(v['type'].object, v['type'].field, v['import_value'], v['padding'])
                if not account_id:
                    partner_debit_id = partner.search([('debitor_number', '=', v['import_value'])])
                    partner_credit_id = partner.search([('creditor_number', '=', v['import_value'])])
                    if partner_debit_id or partner_credit_id:
                        partner_check = True
                    if not partner_check:
                        logs.append({
                            'parent_id': self.id,
                            'line': count,
                            'name': _('%s does not exist. Please Check.' %  v['import_value']),
                            'state': 'error'
                        })
            if v['type'].type == 'counteraccount':
                partner = self.env['res.partner']
                partner_check = False
                account_id = self.get_object(v['type'].object, v['type'].field, v['import_value'], v['padding'])
                if not account_id:
                    partner_debit_id = partner.search([('debitor_number', '=', v['import_value'])])
                    partner_credit_id = partner.search([('creditor_number', '=', v['import_value'])])
                    if partner_debit_id or partner_credit_id:
                        partner_check = True
                    if not partner_check:
                        logs.append({
                            'parent_id': self.id,
                            'line': count,
                            'name': _('%s does not exist. Please Check.' %  v['import_value']),
                            'state': 'error'
                        })
            if v['type'].type == 'move_date':
                try:
                    datetime.strptime(v['import_value'], v['date_format'])
                except:
                    logs.append({
                        'parent_id': self.id,
                        'line': count,
                        'name': _('%s does not fit to %s. Please Check.' % (k, v['date_format'])),
                        'state': 'error'
                    })
            if v['type'].type == 'guid':
                created_guid = self.env['account.move'].search([('syscoon_datev_import_guid', '=', v['import_value'])])
                if created_guid:
                    logs.append({
                        'parent_id': self.id,
                        'line': count,
                        'name': _('%s with GUID %s already exist and can not be imported' % (k, v['import_value'])),
                        'state': 'warning'
                    })
        return logs

    def convert_to_float(self, value):
        if value == '':
            return True
        else:
            return locale.atof(value)

    def check_move_sign(self, value):
        if value.lower() in ['s', 'h']:
            return value.lower()
        else:
            return False

    def get_date(self, format, value):
        move_date = datetime.strptime(value,format)
        if '%y' not in format or '%Y' not in format:
            move_date = move_date.replace(year=self.end_date.year)
        return move_date

    def get_object(self, object, field, value, padding):
        return_object = False
        if object == 'account.tax':
            taxes = self.env[object].search([(field, '=', value)])
            for tax in taxes:
                if tax.price_include:
                    return_object = tax
        elif padding:
            return_object =  self.env[object].search([(field, '=', value.zfill(padding))])
        else:
            return_object =  self.env[object].search([(field, '=', value)])
        return return_object

    # def get_account_types(self):#
    #     types = []
    #     for ref in ACCOUNT_TYPES:
    #         types.append(self.env.ref(ref).id)
    #     return types

    def get_cost_account_types(self):#
        types = []
        for ref in COST_ACCOUNT_TYPES:
            types.append(self.env.ref(ref).id)
        return types

    def create_values(self, list):
        moves = []
        partner = self.env['res.partner']

        for dict in list:
            for k, v in dict.items():
                if v['type'].type == 'move_sign':
                    sign = self.check_move_sign(v['import_value'])

            move = {
                'ref': False,
                'date': False,
                'journal_id': self.journal_id.id,
                'line_ids': [(0, 0 , [])],
                'move_type': 'entry',
                'syscoon_datev_import_id': self.id,
            }

            debit_move_line = {
                'account_id': False,
                'partner_id': False,
                'name': False,
                'analytic_account_id': False,
                'analytic_tag_ids': [(6, 0, [])],
                'tax_ids': [(6, 0, [])],
                'tax_line_id': False,
                'debit': 0.0,
                'credit': 0.0,
                'tax_tag_ids': False
            }

            credit_move_line = {
                'account_id': False,
                'partner_id': False,
                'name': False,
                'analytic_account_id': False,
                'analytic_tag_ids': [(6, 0, [])],
                'tax_ids': [(6, 0, [])],
                'tax_line_id': False,
                'debit': 0.0,
                'credit': 0.0,
                'tax_tag_ids': False,
            }

            discount_move_line = {
                'account_id': False,
                'partner_id': False,
                'name': False,
                'analytic_account_id': False,
                'analytic_tag_ids': [(6, 0, [])],
                'tax_ids': [(6, 0, [])],
                'tax_line_id': False,
                'debit': 0.0,
                'credit': 0.0,
                'tax_tag_ids': False,
            }

            has_currency = False
            discount = False
            taxes = False
            tax_id = False
            tax_direction = False
            opposite_move = False
            account_types = ACCOUNT_TYPES
            COST_ACCOUNT_TYPES = self.get_cost_account_types()

            for k, v in dict.items():
                if v['type'].type == 'currency' and v['import_value']:
                    has_currency = True
                if v['type'].type == 'move_date':
                    move['date'] = self.get_date(v['date_format'], v['import_value'])
                if v['type'].type == 'move_name':
                    debit_move_line['name'] = v['import_value']
                    credit_move_line['name'] = v['import_value']
                if v['type'].type == 'move_ref':
                    move['ref'] = v['import_value']
                if v['type'].type == 'discount_amount':
                    discount = v['import_value']
                if v['type'].type == 'guid':
                    move['syscoon_datev_import_guid'] = v['import_value']

            for k, v in dict.items():
                if has_currency:
                    if v['type'].type == 'base_amount':
                        if sign == 's':
                            debit_move_line['debit'] = self.convert_to_float(v['import_value'])
                            credit_move_line['credit'] = self.convert_to_float(v['import_value'])
                        if sign == 'h':
                            debit_move_line['credit'] = self.convert_to_float(v['import_value'])
                            credit_move_line['debit'] = self.convert_to_float(v['import_value'])
                else:
                    if v['type'].type == 'amount':
                        if sign == 's':
                            debit_move_line['debit'] = self.convert_to_float(v['import_value'])
                            credit_move_line['credit'] = self.convert_to_float(v['import_value'])
                        if sign == 'h':
                            debit_move_line['credit'] = self.convert_to_float(v['import_value'])
                            credit_move_line['debit'] = self.convert_to_float(v['import_value'])

            for k, v in dict.items():
                if v['type'].type == 'account':
                    tax_direction = 'debit_move_line'
                    debit_move_line['account_id'] = self.get_object(v['type'].object, v['type'].field, v['import_value'], v['padding'])
                    if debit_move_line['account_id'].datev_automatic_tax:
                        tax_ids = debit_move_line['account_id'].datev_automatic_tax
                        for tax in tax_ids:
                            if tax.price_include:
                                tax_id = tax
                    if not debit_move_line['account_id']:
                        partner_debit_id = partner.search([('debitor_number', '=', v['import_value'])])
                        partner_credit_id = partner.search([('creditor_number', '=', v['import_value'])])
                        if partner_debit_id:
                            debit_move_line['account_id'] = partner_debit_id.property_account_receivable_id
                            debit_move_line['partner_id'] = partner_debit_id.id
                        if partner_credit_id:
                            debit_move_line['account_id'] = partner_credit_id.property_account_payable_id
                            debit_move_line['partner_id'] = partner_credit_id.id
                if v['type'].type == 'counteraccount':
                    credit_move_line['account_id'] = self.get_object(v['type'].object, v['type'].field, v['import_value'], v['padding'])
                    if credit_move_line['account_id'].datev_automatic_tax:
                        tax_direction = 'credit_move_line'
                        tax_ids = credit_move_line['account_id'].datev_automatic_tax
                        for tax in tax_ids:
                            if tax.price_include:
                                tax_id = tax
                    if not credit_move_line['account_id']:
                        partner_debit_id = partner.search([('debitor_number', '=', v['import_value'])])
                        partner_credit_id = partner.search([('creditor_number', '=', v['import_value'])])
                        if partner_debit_id:
                            credit_move_line['account_id'] = partner_debit_id.property_account_receivable_id
                            credit_move_line['partner_id'] = partner_debit_id.id
                        if partner_credit_id:
                            credit_move_line['account_id'] = partner_credit_id.property_account_payable_id
                            credit_move_line['partner_id'] = partner_credit_id.id
                    if tax_id and not tax_direction:
                        tax_direction = 'credit_move_line'

            for k, v in dict.items():
                if v['type'].type == 'tax_key' and v['import_value']:
                    tax_id = self.get_object(v['type'].object, v['type'].field, v['import_value'], v['padding'])
                if v['type'].type == 'cost1' and v['import_value']:
                    if debit_move_line['account_id'].account_type in COST_ACCOUNT_TYPES:
                        debit_move_line['analytic_account_id'] = self.get_object(v['type'].object, v['type'].field, v['import_value'], v['padding']).id
                    if credit_move_line['account_id'].account_type in COST_ACCOUNT_TYPES:
                        credit_move_line['analytic_account_id'] = self.get_object(v['type'].object, v['type'].field, v['import_value'], v['padding']).id
                if v['type'].type == 'cost2' and v['import_value']:
                    if debit_move_line['account_id'].account_type in COST_ACCOUNT_TYPES:
                        debit_move_line['analytic_tag_ids'] = [(6, 0, self.get_object(v['type'].object, v['type'].field, v['import_value'], v['padding']).ids)]
                    if credit_move_line['account_id'].account_type in COST_ACCOUNT_TYPES:
                        credit_move_line['analytic_tag_ids'] = [(6, 0, self.get_object(v['type'].object, v['type'].field, v['import_value'], v['padding']).ids)]

            if tax_id:
                if not tax_direction:
                    if debit_move_line['account_id'].account_type in ACCOUNT_TYPES:
                        tax_direction = 'debit_move_line'
                if not tax_direction:
                    if credit_move_line['account_id'].account_type in ACCOUNT_TYPES:
                        tax_direction = 'credit_move_line'
                if debit_move_line['account_id'].account_type in ACCOUNT_TYPES and tax_direction == 'debit_move_line':
                    if debit_move_line['debit']:
                        taxes = tax_id.compute_all(debit_move_line['debit'])
                        debit_move_line['debit'] = taxes['total_excluded']
                    if debit_move_line['credit']:
                        taxes = tax_id.compute_all(debit_move_line['credit'])
                        debit_move_line['credit'] = taxes['total_excluded']
                    debit_move_line['tax_ids'] = [(6, 0, tax_id.ids)]
                    debit_move_line['tax_tag_ids'] = [(6, 0, taxes['base_tags'])]
                if credit_move_line['account_id'].account_type in ACCOUNT_TYPES and tax_direction == 'credit_move_line':
                    if credit_move_line['debit']:
                        taxes = tax_id.compute_all(credit_move_line['debit'])
                        credit_move_line['debit'] = taxes['total_excluded']
                    if credit_move_line['credit']:
                        taxes = tax_id.compute_all(credit_move_line['credit'])
                        credit_move_line['credit'] = taxes['total_excluded']
                    credit_move_line['tax_ids'] = [(6, 0, tax_id.ids)]
                    credit_move_line['tax_tag_ids'] = [(6, 0, taxes['base_tags'])]

            for k, v in dict.items():
                if v['type'].type == 'discount_amount' and v['import_value']:
                    discount_move_line['name'] = _('Discount')
                    amount = self.convert_to_float(v['import_value'])
                    if move['ref'] != '0' or move['ref'] != False:
                        opposite_move = self.env['account.move'].search([('datev_ref', '=', move['ref'])])
                    if opposite_move:
                        for l in opposite_move.line_ids:
                            if l.account_id.account_type in ACCOUNT_TYPES:
                                if l.tax_ids:
                                    tax_id = l.tax_ids[0].with_context(force_price_include=True)
                    if tax_id and tax_id.datev_discount_account:
                        for tax in tax_id.datev_discount_account.datev_automatic_tax:
                            if tax.price_include:
                                tax_id = tax
                    taxes = tax_id.compute_all(amount)
                    discount_move_line['account_id'] = tax_id.datev_discount_account.id
                    if debit_move_line['account_id'].account_type in ['receivable', 'payable']:
                        if debit_move_line['credit']:
                            discount_move_line['debit'] = taxes['total_excluded']
                            debit_move_line['credit'] += amount
                        if debit_move_line['debit']:
                            discount_move_line['credit'] = taxes['total_excluded']
                            debit_move_line['debit'] += amount
                    if credit_move_line['account_id'].account_type in ['receivable', 'payable']:
                        if credit_move_line['credit']:
                            discount_move_line['debit'] = taxes['total_excluded']
                            credit_move_line['credit'] += amount
                        if credit_move_line['debit']:
                            discount_move_line['credit'] = taxes['total_excluded']
                            credit_move_line['debit'] += amount
                    discount_move_line['tax_ids'] = [(6, 0, tax_id.ids)]
                    discount_move_line['tax_tag_ids'] = [(6, 0, taxes['base_tags'])]

            if not isinstance(debit_move_line['account_id'], int):
                debit_move_line['account_id'] = debit_move_line['account_id'].id
            if not isinstance(credit_move_line['account_id'], int):
                credit_move_line['account_id'] = credit_move_line['account_id'].id
            move['line_ids'] = [(0, 0, debit_move_line), (0, 0, credit_move_line)]

            if discount_move_line['name']:
                move['line_ids'].append((0, 0, discount_move_line))

            if taxes:
                tax_move_line = {}
                for tax in taxes['taxes']:
                    if tax['account_id']:
                        tax_move_line['account_id'] = tax['account_id']
                        tax_move_line['name'] = tax['name']
                        tax_move_line['tax_base_amount'] = tax['base']
                        tax_move_line['tax_tag_ids'] = [(6, 0, tax['tag_ids'])]
                        tax_move_line['tax_line_id'] = tax['id']
                        tax_move_line['tax_group_id'] = tax_id.tax_group_id.id
                        tax_move_line['tax_repartition_line_id'] = tax['tax_repartition_line_id']
                        if debit_move_line['tax_tag_ids']:
                            if debit_move_line['debit']:
                                if tax['amount'] < 0.0:
                                    tax_move_line['credit'] = -tax['amount']
                                else:
                                    tax_move_line['debit'] = tax['amount']
                            if debit_move_line['credit']:
                                if tax['amount'] < 0.0:
                                    tax_move_line['debit'] = -tax['amount']
                                else:
                                    tax_move_line['credit'] = tax['amount']
                        if credit_move_line['tax_tag_ids']:
                            if credit_move_line['debit']:
                                if tax['amount'] < 0.0:
                                    tax_move_line['credit'] = -tax['amount']
                                else:
                                    tax_move_line['debit'] = tax['amount']
                            if credit_move_line['credit']:
                                if tax['amount'] < 0.0:
                                    tax_move_line['debit'] = -tax['amount']
                                else:
                                    tax_move_line['credit'] = tax['amount']
                        if discount_move_line['tax_tag_ids']:
                            if discount_move_line['debit']:
                                if tax['amount'] < 0.0:
                                    tax_move_line['credit'] = -tax['amount']
                                else:
                                    tax_move_line['debit'] = tax['amount']
                            if discount_move_line['credit']:
                                if tax['amount'] < 0.0:
                                    tax_move_line['debit'] = -tax['amount']
                                else:
                                    tax_move_line['credit'] = tax['amount']
                        move['line_ids'].append((0, 0, tax_move_line))
            for ml in move['line_ids']:
                if not ml[2]['account_id'] and self.template_id.ignore_incomplete_moves:
                    remove = True
                    self.env['syscoon.datev.import.log'].create({
                        'parent_id': self.id,
                        'name': _('Move %s not imported' % move['ref']),
                        'state': 'warning',
                    })
                else:
                    remove = False
            existing_guid = False
            if move.get('syscoon_datev_import_guid'):
                existing_guid = self.env['account.move'].search([('syscoon_datev_import_guid', '=', move['syscoon_datev_import_guid'])])
            if not remove and not existing_guid:
                moves.append(move)
        return moves

    def create_moves(self, moves):
        AccountMove = self.env['account.move'].with_context(default_journal_id=self.journal_id.id)
        move_ids = AccountMove.sudo().create(moves)
        for mv in move_ids:
            self.env['syscoon.datev.import.log'].create({
                'parent_id': self.id,
                'name': _('Move %s imported' % mv['ref']),
                'state': 'info',
            })
        return move_ids

class ImportDatevLog(models.Model):
    """
    Loglineobject for import
    """
    _name = 'syscoon.datev.import.log'
    _order = 'id desc'
    _description = 'Object for loggin the import'

    name = fields.Text('Name')
    line = fields.Char('Line')
    parent_id = fields.Many2one('syscoon.datev.import', 'Import')
    date = fields.Datetime('Time', readonly=True, default=lambda *a: time.strftime('%Y-%m-%d %H:%M:%S'))
    state = fields.Selection([('info', 'Info'), ('error', 'Error'), ('standard', 'Ok'), ('warning', 'Warning')],
                             'State', index=True, readonly=True, default='info')
