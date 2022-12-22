# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api, _
from odoo.tools import float_repr, float_split_str

import re
from lxml import etree

EU_VAT = ['BE', 'BG', 'DK', 'DE', 'EE', 'FI', 'FR', 'EL', 'GB', 'IE',
                'IT', 'HR', 'LV', 'LT', 'LU', 'MT', 'NL', 'AT', 'PL', 'PT',
                'RO', 'SE', 'SK', 'SI', 'ES', 'CZ', 'HU', 'CY']

class syscoonFinanceinterfaceXML(models.TransientModel):
    _name = 'syscoon.financeinterface.xml'
    _description = 'definitions for the syscoon financeinterface DATEV XML-export'

    def create_invoice_xml(self, move_id, invoice_mode):
        xml = self.make_invoice_xml(move_id, invoice_mode)
        invoice = etree.tostring(xml, pretty_print = True, xml_declaration = True, encoding = 'UTF-8')
        return invoice

    def get_subelement(self, tag, d):
        elem = etree.Element(tag)
        for key, val in d.items():
            if val:
                elem.attrib[key] = self.make_string(val)
            if key == 'tax' and val == 0.0:
                elem.attrib[key] = self.make_string(val)
        return elem

    def make_string(self, val):
        if type(val) == float:
            return format(val, '.2f')
        else:
            return str(val)

    def get_invoice_info(self, move_id, invoice_mode):
        vals = {}
        vals['invoice_date'] = move_id.invoice_date
        if move_id.move_type in ['out_invoice', 'in_invoice']:
            vals['invoice_type'] = 'Rechnung'
        if move_id.move_type in ['out_refund', 'in_refund']:
            vals['invoice_type'] = 'Gutschrift/Rechnungskorrektur'
        if move_id.move_type in ['in_invoice', 'in_refund'] and move_id.ref:
            vals['invoice_id'] = re.sub(r'[^\w]', '', move_id.ref[:36])
        else:
            vals['invoice_id'] = re.sub(r'[^\w]', '', move_id.name[:36])
        vals['delivery_date'] = str(move_id.date)
        return vals

    def get_accounting_info(self, move_id, invoice_mode):
        vals = {}
        if move_id.move_type == 'out_invoice':
            vals['booking_text'] = 'Erlöse'
        if move_id.move_type == 'out_refund':
            vals['booking_text'] = 'Gutschrift Erlöse'
        if move_id.move_type == 'in_invoice':
            vals['booking_text'] = 'Aufwand'
        if move_id.move_type == 'in_refund':
            vals['booking_text'] = 'Gutschrift Aufwand'
        return vals

    def get_invoice_party(self, move_id, invoice_mode):
        if move_id.move_type in ['out_invoice', 'out_refund']:
            ip = move_id.commercial_partner_id
            booking_info = True
        if move_id.move_type in ['in_invoice', 'in_refund']:
            ip = move_id.company_id
            booking_info = False
        vals = {}
        if ip.vat and ip.vat[:2] in EU_VAT:
            vals['vat_id'] = ip.vat
        vals['address'] = {}
        if ip.name:
            vals['address']['name'] = ip.name[:50]
        elif ip.parent_id.name:
            vals['address']['name'] = ip.parent_id.name[:50]
        if ip.street:
            vals['address']['street'] = ip.street[:40]
        if ip.zip:
            vals['address']['zip'] = ip.zip
        if ip.city:
            vals['address']['city'] = ip.city
        if ip.country_id:
            vals['address']['country'] = ip.country_id.code
        if invoice_mode == 'extended':
            if ip.phone:
                vals['address']['phone'] = ip.phone[:20]
            if 'ref' in ip._fields and ip.ref:
                if ip.ref != ip.customer_number:
                    vals['address']['party_id'] = ip.ref[:15]
            if booking_info:
                if move_id.partner_bank_id:
                    bank = move_id.partner_bank_id
                    if bank.acc_type == 'iban' and bank.bank_id.name:
                        vals['account'] = {}
                        if bank.sanitized_acc_number:
                            vals['account']['iban'] = bank.sanitized_acc_number
                        if bank.bank_id.bic:
                            vals['account']['swiftcode'] = bank.bank_id.bic
                        if bank.bank_id.name:
                            vals['account']['bank_name'] = bank.bank_id.name[:27]
                vals['booking_info_bp'] = {}
                vals['booking_info_bp']['bp_account_no'] = ip.debitor_number or ip.property_account_receivable_id.code
        return vals

    def get_supplier_party(self, move_id, invoice_mode):
        if move_id.move_type in ['out_invoice', 'out_refund']:
            sp =  move_id.company_id
            booking_info = False
        if move_id.move_type in ['in_invoice', 'in_refund']:
            sp = move_id.commercial_partner_id
            booking_info = True
        vals = {}
        if sp.vat and sp.vat[:2] in EU_VAT:
            vals['vat_id'] = sp.vat
        vals['address'] = {}
        if sp.name:
            vals['address']['name'] = sp.name[:50]
        if sp.street:
            vals['address']['street'] = sp.street[:40]
        if sp.zip:
            vals['address']['zip'] = sp.zip
        if sp.city:
            vals['address']['city'] = sp.city
        if sp.country_id:
            vals['address']['country'] = sp.country_id.code
        if invoice_mode == 'extended':
            if sp.phone:
                vals['address']['phone'] = sp.phone[:20]
            if 'ref' in sp._fields and sp.ref:
                vals['address']['party_id'] = sp.ref[:15]
            if booking_info:
                if move_id.partner_bank_id:
                    bank = move_id.partner_bank_id
                    if bank.acc_type == 'iban' and bank.bank_id.name:
                        vals['account'] = {}
                        if bank.sanitized_acc_number:
                            vals['account']['iban'] = bank.sanitized_acc_number
                        if bank.bank_id.bic:
                            vals['account']['swiftcode'] = bank.bank_id.bic
                        if bank.bank_id.name:
                            vals['account']['bank_name'] = bank.bank_id.name[:27]
                vals['booking_info_bp'] = {}
                vals['booking_info_bp']['bp_account_no'] = sp.creditor_number or sp.property_account_payable_id.code
                vals['party_id'] = sp.supplier_number or vals['booking_info_bp']['bp_account_no']
        return vals

    def get_payment_conditions(self, move_id):
        vals = {}
        vals['currency'] = move_id.currency_id.name
        vals['due_date'] = move_id.invoice_date_due
        vals['payment_conditions_text'] = move_id.invoice_payment_term_id.name
        if move_id.invoice_payment_term_id.datev_payment_conditons_id:
            vals['payment_conditions_id'] = move_id.invoice_payment_term_id.datev_payment_conditons_id
        return vals

    def get_invoice_item_list(self, move_id, invoice_mode):
        vals = []
        total_invoice_amount = 0.0
        for line in move_id.invoice_line_ids:
            if not line.display_type and not line.price_subtotal == 0.0:
                item = self._get_invoice_item_list_item(move_id, line, invoice_mode)
                vals.append(item)
        if self.env.company.export_xml_group_lines and invoice_mode == 'extended':
            new_vals = []
            for val in vals:
                if not any(nv['price_line_amount']['tax'] == val['price_line_amount']['tax']
                           and nv['accounting_info']['account_no'] == val['accounting_info']['account_no']
                           and nv['accounting_info']['cost_category_id'] == val['accounting_info']['cost_category_id']
                           and nv['accounting_info']['cost_category_id2'] == val['accounting_info']['cost_category_id2']
                           and nv['accounting_info']['bu_code'] == val['accounting_info']['bu_code']
                           for nv in new_vals):
                    new_vals.append(val)
                else:
                    for nv in new_vals:
                        if nv['price_line_amount']['tax'] == val['price_line_amount']['tax'] \
                           and nv['accounting_info']['account_no'] == val['accounting_info']['account_no'] \
                           and nv['accounting_info']['cost_category_id'] == val['accounting_info']['cost_category_id'] \
                           and nv['accounting_info']['cost_category_id2'] == val['accounting_info']['cost_category_id2'] \
                           and nv['accounting_info']['bu_code'] == val['accounting_info']['bu_code']:
                            nv['quantity'] += val['quantity']
                            if val['price_line_amount'].get('tax_amount'):
                                nv['price_line_amount']['tax_amount'] += val['price_line_amount']['tax_amount']
                            nv['price_line_amount']['gross_price_line_amount'] += val['price_line_amount']['gross_price_line_amount']
                            nv['price_line_amount']['net_price_line_amount'] += val['price_line_amount']['net_price_line_amount']
                            break
            for nvs in new_vals:
                nvs['quantity'] = 1.0
                if not nvs['price_line_amount'].get('tax_amount'):
                    total_invoice_amount += nvs['price_line_amount']['gross_price_line_amount']
                else:
                    nvs['price_line_amount']['gross_price_line_amount'] = move_id.currency_id.round(nvs['price_line_amount']['net_price_line_amount'] * (100 + nvs['price_line_amount']['tax']) / 100)
                    nvs['price_line_amount']['tax_amount'] = nvs['price_line_amount']['gross_price_line_amount'] - nvs['price_line_amount']['net_price_line_amount']
                    total_invoice_amount += nvs['price_line_amount']['gross_price_line_amount']
                    if nvs['price_line_amount'].get('tax_amount') and float_repr(nvs['price_line_amount']['tax_amount'], 2) in ['0.00', '-0.00']:
                        nvs['price_line_amount'].pop('tax_amount')
            vals = new_vals
        if float_repr(total_invoice_amount, 2) != float_repr(move_id.amount_total, 2):
            if move_id.move_type in ['in_refund', 'out_refund']:
                sign = -1
            else:
                sign = 1
            difference = move_id.currency_id.round(total_invoice_amount - (move_id.amount_total * sign))
            last_val = vals[-1]
            del vals[-1]
            if last_val['price_line_amount'].get('tax_amount'):
                last_val['price_line_amount']['tax_amount'] = move_id.currency_id.round(last_val['price_line_amount']['tax_amount'] - difference)
            if last_val['price_line_amount'].get('gross_price_line_amount',0.0):
                last_val['price_line_amount']['gross_price_line_amount'] = move_id.currency_id.round(last_val['price_line_amount'].get('gross_price_line_amount',0.0) - difference)
            vals.append(last_val)
        return vals

    def _get_invoice_item_list_item(self, move_id, line, invoice_mode):
        item = {}
        item['description_short'] = line.name and line.name[:40] or _('Description')
        item['quantity'] = line.quantity or 1.0
        item['price_line_amount'] = {}
        item['price_line_amount']['tax'] = line.tax_ids and line.tax_ids[0].amount or 0.0
        if invoice_mode == 'extended':
            if move_id.move_type in ['out_refund', 'in_refund']:
                if move_id.currency_id.round(line.price_total - line.price_subtotal) != 0.0:
                    item['price_line_amount']['tax_amount'] = - (line.price_total - line.price_subtotal)
                item['price_line_amount']['gross_price_line_amount'] = - line.price_total
                item['price_line_amount']['net_price_line_amount'] = - line.price_subtotal
            else:
                if move_id.currency_id.round(line.price_total - line.price_subtotal) != 0.0:
                    item['price_line_amount']['tax_amount'] = line.price_total - line.price_subtotal
                item['price_line_amount']['gross_price_line_amount'] = line.price_total
                item['price_line_amount']['net_price_line_amount'] = line.price_subtotal
            item['price_line_amount']['currency'] = line.currency_id.name or 'EUR'
            item['accounting_info'] = {}
            item['accounting_info']['account_no'] = line.account_id.code.lstrip('0')
            if line.currency_id and line.currency_id != line.company_id.currency_id and line.amount_currency != 0.0:
                item['accounting_info']['exchange_rate'] = "{:.6f}".format(line.company_id.currency_id._convert(1.0, line.currency_id, line.company_id, line.date, round=False))
            item['accounting_info']['booking_text'] = line.name and line.name[:60] or _('Description')
            if not line.account_id.datev_automatic_account:
                if line.tax_ids and line.tax_ids[0].datev_tax_key != '0':
                    item['accounting_info']['bu_code'] = line.tax_ids[0].datev_tax_key
                else:
                    item['accounting_info']['bu_code'] = False
            else:
                item['accounting_info']['bu_code'] = False
            if move_id.company_id.export_xml_analytic_accounts:
                if line.analytic_account_id and line.analytic_account_id.code:
                    item['accounting_info']['cost_category_id'] = line.analytic_account_id.code
                if line.analytic_tag_ids:
                    item['accounting_info']['cost_category_id2'] = line.analytic_tag_ids[0].name[:35]
        return item

    def get_total_amount(self, move_id, invoice_mode):
        vals = {}
        if move_id.move_type in ['out_refund', 'in_refund']:
            vals['total_gross_amount_excluding_third-party_collection'] = - move_id.amount_total
        else:
            vals['total_gross_amount_excluding_third-party_collection'] = move_id.amount_total
        if invoice_mode == 'extended':
            if move_id.move_type in ['out_refund', 'in_refund']:
                vals['net_total_amount'] = - move_id.amount_untaxed
            else:
                vals['net_total_amount'] = move_id.amount_untaxed
        vals['currency'] = move_id.currency_id.name or 'EUR'
        tax_lines = move_id.line_ids.filtered(lambda line: line.tax_line_id)
        tax_key_lines = move_id.line_ids.filtered(lambda line: line.tax_ids)
        vals['tax_line'] = []
        currency_rate = 1.0
        if move_id.currency_id and move_id.currency_id != self.env.company.currency_id:
            currency_rate = move_id.company_id.currency_id._convert(1.0, move_id.currency_id, move_id.company_id, move_id.date, round=False)
        res = {}
        done_taxes = set()
        for line in tax_lines:
            res.setdefault(line.tax_line_id.tax_group_id, {'rate': 0.0, 'base': 0.0, 'amount': 0.0, 'currency_amount': 0.0})
            res[line.tax_line_id.tax_group_id]['rate'] = line.tax_line_id.amount
            res[line.tax_line_id.tax_group_id]['amount'] += line.price_subtotal
            tax_key_add_base = tuple([line.tax_line_id.id])
            if tax_key_add_base not in done_taxes:
                # The base should be added ONCE
                res[line.tax_line_id.tax_group_id]['base'] += line.tax_base_amount * currency_rate
                done_taxes.add(tax_key_add_base)
        for line in tax_key_lines:
            res.setdefault(line.tax_ids[0].tax_group_id, {'rate': 0.0, 'base': 0.0, 'amount': 0.0, 'currency_amount': 0.0})
            if line.tax_ids[0].amount == 0.0:
                res[line.tax_ids[0].tax_group_id]['base'] += (line.debit + line.credit) * currency_rate
                res[line.tax_ids[0].tax_group_id]['currency_amount'] += - line.amount_currency if line.amount_currency < 0.0 else line.amount_currency
        res = sorted(res.items(), key=lambda l: l[0].sequence)
        for group, amounts in res:
            line_vals = {}
            line_vals['tax'] = amounts['rate']
            line_vals['currency'] = move_id.currency_id.name
            if amounts['rate'] != 0.0:
                currency_rate = 1.0
            if amounts['currency_amount'] and amounts['base'] != amounts['currency_amount']:
                amounts['base'] = amounts['currency_amount']
            if invoice_mode == 'extended':
                if move_id.move_type in ['out_refund', 'in_refund']:
                    line_vals['net_price_line_amount'] = - amounts['base']
                    line_vals['gross_price_line_amount'] = - amounts['base'] + (amounts['amount'] * currency_rate)
                else:
                    line_vals['net_price_line_amount'] = amounts['base']
                    line_vals['gross_price_line_amount'] = amounts['base'] + (amounts['amount'] * currency_rate)
                if amounts['amount'] > 0.0:
                    if move_id.move_type in ['out_refund', 'in_refund']:
                        line_vals['tax_amount'] = - amounts['amount']
                    else:
                        line_vals['tax_amount'] = amounts['amount']
            vals['tax_line'].append(line_vals)
        if not vals['tax_line']:
            line_vals = {}
            line_vals['tax'] = 0.0
            line_vals['currency'] = move_id.currency_id.name
            vals['tax_line'].append(line_vals)
        return vals

    def get_additional_footer(self, move_id):
        text = self.env['syscoon.financeinterface'].text_from_html(
            move_id.narration, max_chars=60)
        if text:
            vals = {
                'type': 'text',
                'context': text,
            }
            return vals
        else:
            return False

    def make_invoice_xml(self, move_id, invoice_mode):
        attr_qname = etree.QName('http://www.w3.org/2001/XMLSchema-instance', 'schemaLocation')
        nsmap = {'xsi': 'http://www.w3.org/2001/XMLSchema-instance',
                 None: 'http://xml.datev.de/bedi/tps/invoice/v050'}

        invoice = etree.Element('invoice',
            {attr_qname: 'http://xml.datev.de/bedi/tps/invoice/v050 Belegverwaltung_online_invoice_v050.xsd'},
            nsmap=nsmap)
        invoice.attrib['generator_info'] = 'Odoo 13'
        invoice.attrib['generating_system'] = 'Odoo-ERP Software'
        invoice.attrib['description'] = 'DATEV Import invoices'
        invoice.attrib['version'] = '5.0'
        invoice.attrib['xml_data'] = 'Kopie nur zur Verbuchung berechtigt nicht zum Vorsteuerabzug'

        invoice_info = etree.SubElement(invoice, 'invoice_info')
        for key, val in self.get_invoice_info(move_id, invoice_mode).items():
            invoice_info.attrib[key] = self.make_string(val)

        if invoice_mode == 'extended':
            account_info = etree.SubElement(invoice, 'accounting_info')
            for key, val in self.get_accounting_info(move_id,
                    invoice_mode).items():
                account_info.attrib[key] = self.make_string(val)

        invoice_party = etree.SubElement(invoice, 'invoice_party')
        for key, val in self.get_invoice_party(move_id, invoice_mode).items():
            if key == 'vat_id':
                invoice_party.attrib[key] = self.make_string(val)
            if key == 'address':
                invoice_party.append(self.get_subelement(key, val))
            if key == 'account':
                invoice_party.append(self.get_subelement(key, val))
            if key == 'booking_info_bp':
                invoice_party.append(self.get_subelement(key, val))

        supplier_party = etree.SubElement(invoice, 'supplier_party')
        for key, val in self.get_supplier_party(move_id, invoice_mode).items():
            if key == 'vat_id':
                supplier_party.attrib[key] = self.make_string(val)
            if key == 'address':
                supplier_party.append(self.get_subelement(key, val))
            if key == 'account':
                supplier_party.append(self.get_subelement(key, val))
            if key == 'booking_info_bp':
                supplier_party.append(self.get_subelement(key, val))

        if invoice_mode == 'extended' and move_id.invoice_payment_term_id:
            payment_conditions = etree.SubElement(invoice, 'payment_conditions')
            for key, val in self.get_payment_conditions(move_id).items():
                payment_conditions.attrib[key] = self.make_string(val)

        for item in self.get_invoice_item_list(move_id, invoice_mode):
            invoice_item_list = etree.SubElement(invoice, 'invoice_item_list')
            for key, val in item.items():
                if key == 'description_short':
                    invoice_item_list.attrib[key] = self.make_string(val)
                if key == 'quantity':
                    invoice_item_list.attrib[key] = self.make_string(val)
                if key == 'price_line_amount':
                    invoice_item_list.append(self.get_subelement(key, val))
                if key == 'accounting_info':
                    invoice_item_list.append(self.get_subelement(key, val))

        total_amount = etree.SubElement(invoice, 'total_amount')
        for key, val in self.get_total_amount(move_id, invoice_mode).items():
            if key != 'tax_line':
                total_amount.attrib[key] = self.make_string(val)
            if key == 'tax_line':
                for line in val:
                    total_amount.append(self.get_subelement(key, line))

        if move_id.narration:
            vals = self.get_additional_footer(move_id)
            if vals:
                additional_info_footer = etree.SubElement(invoice,
                    'additional_info_footer')
                additional_info_footer.attrib['type'] = vals['type']
                additional_info_footer.attrib['content'] = vals['context']

        return invoice

    def create_documents_xml(self, docs, timestamp):
        xml = self.make_documents_xml(docs, timestamp)
        documents = etree.tostring(xml, pretty_print = True, 
            xml_declaration = True, encoding = 'UTF-8')
        return documents

    def make_documents_xml(self, docs, timestamp):
        attr_qname = etree.QName('http://www.w3.org/2001/XMLSchema-instance', 
            'schemaLocation')
        qname = etree.QName('http://www.w3.org/2001/XMLSchema-instance', 'type')
        nsmap = {'xsi': 'http://www.w3.org/2001/XMLSchema-instance',
                 None: 'http://xml.datev.de/bedi/tps/document/v05.0'}

        archive = etree.Element('archive',
            {attr_qname: 'http://xml.datev.de/bedi/tps/document/v05.0 document_v050.xsd'},
            nsmap=nsmap)
        archive.attrib['version'] = '5.0'
        archive.attrib['generatingSystem'] = 'Odoo-ERP Software'
        header = etree.SubElement(archive, 'header')
        date = etree.SubElement(header, 'date')
        date.text = str(timestamp)
        description = etree.SubElement(header, 'description')
        description.text = 'Rechnungsexport'
        content = etree.SubElement(archive, 'content')
        for doc in docs:
            document = etree.SubElement(content, 'document')
            if doc.inv.company_id.datev_use_bedi and doc.inv.datev_bedi:
                document.attrib['guid'] = doc.inv.datev_bedi
            extension = etree.Element('extension', {qname: 'Invoice'})
            extension.attrib['datafile'] = doc.xml_path
            property = etree.SubElement(extension, 'property')
            property.attrib['key'] = 'InvoiceType'
            property.attrib['value'] = self.get_document_value(doc.inv)
            document.append(extension)
            extension = etree.Element('extension', {qname: 'File'})
            extension.attrib['name'] = doc.pdf_path
            document.append(extension)
        return archive

    def get_document_value(self, move_id):
        if move_id.move_type in ['out_invoice', 'out_refund']:
            return 'Outgoing'
        else:
            return 'Incoming'

