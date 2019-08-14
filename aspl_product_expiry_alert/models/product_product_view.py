# -*- coding: utf-8 -*-
#################################################################################
# Author      : Acespritech Solutions Pvt. Ltd. (<www.acespritech.com>)
# Copyright(c): 2012-Present Acespritech Solutions Pvt. Ltd.
# All Rights Reserved.
#
# This program is copyright property of the author mentioned above.
# You can`t redistribute it and/or modify it.
#
#################################################################################
import ast
import copy
from odoo import fields, models, api, _
from datetime import datetime, date, timedelta
from itertools import groupby
from odoo.exceptions import ValidationError


class StockLocation(models.Model):
    _inherit = 'stock.location'

    @api.multi
    def get_warehouse_expiry_detail(self, company_id):
        quant_sql = '''
                    SELECT sq.location_id as location_id, sum(sq.quantity) as expire_count, sw.name as warehouse_name
                    FROM stock_warehouse sw 
                    LEFT JOIN stock_location sl on sl.id = sw.lot_stock_id
                    LEFT JOIN stock_quant sq on sq.location_id = sl.id
                    WHERE sq.state_check = 'near_expired'
                    AND sw.company_id = %s
                    GROUP BY sq.location_id,sw.name;
                ''' % (company_id)
        self._cr.execute(quant_sql)
        warehouse_near_expire = self._cr.dictfetchall()
        return warehouse_near_expire

    @api.multi
    def get_location_detail(self, company_id):
        quant_sql = '''
                    SELECT sq.location_id as location_id, sum(sq.quantity) as expire_count , sl.complete_name as location_name
                    FROM stock_quant sq
                    LEFT JOIN stock_location sl on sl.id = sq.location_id
                    WHERE sl.usage = 'internal'
                    AND sl.company_id = %s
                    AND sl.active = True
                    AND sq.state_check = 'near_expired'
                    GROUP BY sq.location_id,sl.complete_name
                ''' % (company_id)
        self._cr.execute(quant_sql)
        location_near_expire = self._cr.dictfetchall()
        return location_near_expire


class StockQuantity(models.Model):
    _inherit = 'stock.quant'

    state_check = fields.Selection(related='lot_id.state_check', string="state", store=True)


class ProductProduct(models.Model):
    _inherit = 'product.product'

    near_expire = fields.Integer(string='Near Expire', compute='check_near_expiry')
    expired = fields.Integer(string='Expired', compute='check_expiry')

    def get_near_expiry(self):
        stock_production_lot_obj = self.env['stock.production.lot']
        if self.tracking != 'none':
            today_date = date.today()
            stock_lot = stock_production_lot_obj.search([('product_id', 'in', self.ids)])
            for each_stock_lot in stock_lot.filtered(lambda l: l.alert_date):
                alert_date = datetime.strptime(str(each_stock_lot.alert_date), '%Y-%m-%d %H:%M:%S').date()
                if each_stock_lot.life_date:
                    life_date = datetime.strptime(str(each_stock_lot.life_date), '%Y-%m-%d %H:%M:%S').date()
                    if life_date >= today_date:
                        stock_production_lot_obj |= each_stock_lot
        return stock_production_lot_obj

    def get_expiry(self):
        stock_production_lot_obj = self.env['stock.production.lot']
        if self.tracking != 'none':
            today_date = date.today()
            stock_lot = self.env['stock.production.lot'].search([('product_id', 'in', self.ids)])
            for each_stock_lot in stock_lot.filtered(lambda l: l.life_date):
                life_date = datetime.strptime(str(each_stock_lot.life_date), '%Y-%m-%d %H:%M:%S').date()
                if life_date < today_date:
                    stock_production_lot_obj |= each_stock_lot
        return stock_production_lot_obj

    @api.one
    def check_near_expiry(self):
        stock_production_lot_obj = self.get_near_expiry()
        self.near_expire = len(stock_production_lot_obj)

    @api.one
    def check_expiry(self):
        stock_production_lot_obj = self.get_expiry()
        self.expired = len(stock_production_lot_obj)

    @api.multi
    def nearly_expired(self):
        stock_production_lot_obj = self.get_near_expiry()
        action = self.env.ref('stock.action_production_lot_form').read()[0]
        action['domain'] = [('id', 'in', [each_lot.id for each_lot in stock_production_lot_obj])]
        return action

    @api.multi
    def product_expired(self):
        stock_production_lot_obj = self.get_expiry()
        action = self.env.ref('stock.action_production_lot_form').read()[0]
        action['domain'] = [('id', 'in', [each_lot.id for each_lot in stock_production_lot_obj])]
        return action

    @api.multi
    def category_expiry(self, company_id):
        quant_sql = '''
                    SELECT pt.name as product_name, sq.quantity as quantity, pc.name as categ_name, spl.id as lot_id
                    FROM stock_quant sq
                    LEFT JOIN stock_production_lot spl on spl.id = sq.lot_id
                    LEFT JOIN product_product pp on pp.id = sq.product_id
                    LEFT JOIN product_template pt on pt.id = pp.product_tmpl_id
                    LEFT JOIN product_category pc on pc.id = pt.categ_id
                    WHERE pt.tracking != 'none'
                    AND spl.life_date is not NULL 
                    AND sq.state_check = 'near_expired'
                    AND sq.company_id = %s
                    AND spl.life_date::Date >= current_date;
                ''' % (company_id)
        self._cr.execute(quant_sql)
        result = self._cr.dictfetchall()
        return result

    @api.model
    def search_product_expiry(self):
        today = datetime.today()
        today_end_date = datetime.strftime(today, "%Y-%m-%d 23:59:59")
        today_date = datetime.strftime(today, "%Y-%m-%d 00:00:00")
        company_id = self.env.user.company_id.id
        categ_nearexpiry_data = self.category_expiry(company_id)
        location_obj = self.env['stock.location']
        location_detail = location_obj.get_location_detail(company_id)
        warehouse_detail = location_obj.get_warehouse_expiry_detail(company_id)

        exp_in_day = {}
        product_expiry_days_ids = self.env['product.expiry.config'].search([('active', '=', True)])
        if product_expiry_days_ids:
            for each in product_expiry_days_ids:
                exp_in_day[int(each.no_of_days)] = 0

        exp_in_day_detail = copy.deepcopy(exp_in_day)
        date_add = datetime.today() + timedelta(days=1)
        today_date_exp = datetime.strftime(date_add, "%Y-%m-%d 00:00:00")
        today_date_end_exp = datetime.strftime(date_add, "%Y-%m-%d 23:59:59")

        for exp_day in exp_in_day:
            product_id_list = []
            exp_date = datetime.today() + timedelta(days=exp_day)
            today_exp_date = datetime.strftime(exp_date, "%Y-%m-%d 23:59:59")
            if today_date_end_exp == today_exp_date:
                self._cr.execute("select sq.lot_id "
                                 "from stock_quant sq left join stock_production_lot spl on spl.id = sq.lot_id "
                                 "where spl.life_date >= '%s'" % today_date_exp + " and"
                                 " spl.life_date <= '%s'" % today_exp_date + "and sq.company_id = '%s'" % company_id + "group by sq.lot_id")
            else:
                self._cr.execute("select sq.lot_id "
                                 "from stock_quant sq left join stock_production_lot spl on spl.id = sq.lot_id "
                                 "where spl.life_date >= '%s'" % today_date + " and"
                                 " spl.life_date <= '%s'" % today_exp_date + "and"
                                 " sq.company_id = '%s'" % company_id + "group by sq.lot_id")
            result = self._cr.fetchall()

            for each in result:
                for each_in in each:
                    product_id_list.append(each_in)
            product_config_color_id = self.env['product.expiry.config'].search([('no_of_days', '=',exp_day),('active', '=', True)], limit=1)
            exp_in_day_detail[exp_day] = {'product_id': product_id_list, 'color': product_config_color_id.block_color, 'text_color': product_config_color_id.text_color}
            exp_in_day[exp_day] = len(result)

        category_list = copy.deepcopy(categ_nearexpiry_data)
        category_res = []
        key = lambda x: x['categ_name']

        for k, v in groupby(sorted(category_list, key=key), key=key):
            qty = 0
            stock_lot = []
            for each in v:
                qty += float(each['quantity'])
                stock_lot.append(each['lot_id'])
            category_res.append({'categ_name': k, 'qty': qty, 'id': stock_lot})

        exp_in_day['expired'] = self.env['stock.production.lot'].search_count([('state_check', '=', 'expired')])
        list_near_expire = []
        quant_sql = '''
                    SELECT sq.lot_id as lot_id
                    FROM stock_quant sq
                    LEFT JOIN stock_production_lot spl on spl.id = sq.lot_id
                    WHERE sq.state_check = 'near_expired'
                    AND sq.company_id = %s
                    AND spl.life_date >= '%s' 
                    AND spl.life_date <= '%s' 
                ''' % (company_id, today_date, today_end_date)
        self._cr.execute(quant_sql)
        quant_detail = self._cr.dictfetchall()

        for each_quant in quant_detail:
            list_near_expire.append(each_quant.get('lot_id'))

        exp_in_day['day_wise_expire'] = exp_in_day_detail
        exp_in_day['near_expired'] = len(set(list_near_expire))
        exp_in_day['near_expire_display'] = list_near_expire
        exp_in_day['category_near_expire'] = category_res
        exp_in_day['location_wise_expire'] = location_detail
        exp_in_day['warehouse_wise_expire'] = warehouse_detail
        return exp_in_day

    @api.multi
    def graph_date(self, start, end):
        company_id = self.env.user.company_id.id
        graph_data_list = []
        start_date = datetime.strptime(start, '%Y-%m-%d').date()
        new_start_date = datetime.strftime(start_date, "%Y-%m-%d %H:%M:%S")
        end_date = datetime.strptime(end, '%Y-%m-%d').date()
        new_end_date = datetime.strftime(end_date, "%Y-%m-%d 23:59:59")

        sql = '''SELECT pt.name as product_name, sum(sq.quantity) AS qty
            FROM stock_quant sq
            LEFT JOIN stock_production_lot spl on spl.id = sq.lot_id
            LEFT JOIN product_product AS pp ON pp.id = spl.product_id
            LEFT JOIN product_template AS pt ON pt.id = pp.product_tmpl_id
            WHERE sq.company_id = %s
            AND sq.state_check is NOT NULL
            AND pt.tracking != 'none'
            AND spl.life_date BETWEEN '%s' AND '%s'
            GROUP BY pt.name;
        ''' % (company_id, new_start_date, new_end_date)
        self._cr.execute(sql)
        data_res = self._cr.dictfetchall()

        return data_res

    @api.model
    def expiry_product_alert(self):
        email_notify_date = None
        notification_days = self.env['ir.config_parameter'].sudo().get_param(
            'aspl_product_expiry_alert.email_notification_days')

        if notification_days:
            email_notify_date = date.today() + timedelta(days=int(notification_days))
            start_email_notify_date = datetime.strftime(date.today(), "%Y-%m-%d %H:%M:%S")
            end_email_notify_date = datetime.strftime(email_notify_date, "%Y-%m-%d 23:59:59")

            res_user_ids = ast.literal_eval(
                self.env['ir.config_parameter'].sudo().get_param('aspl_product_expiry_alert.res_user_ids'))

            SQL = """SELECT sl.name AS stock_location, pt.name AS Product,pp.id AS product_id, 
                        CAST(lot.life_date AS DATE),lot.name lot_number, sq.quantity AS Quantity
                        FROM stock_quant AS sq
                        INNER JOIN stock_production_lot AS lot ON lot.id = sq.lot_id 
                        INNER JOIN stock_location AS sl ON sl.id = sq.location_id
                        INNER JOIN product_product AS pp ON pp.id = lot.product_id
                        INNER JOIN product_template AS pt ON pt.id = pp.product_tmpl_id
                        WHERE sl.usage = 'internal' AND pt.tracking != 'none' AND 
                        lot.life_date BETWEEN '%s' AND '%s'
                    """ %(start_email_notify_date,end_email_notify_date)
            self._cr.execute(SQL)
            near_expiry_data_list = self._cr.dictfetchall()
            email_list = []
            template_id = self.env.ref('aspl_product_expiry_alert.email_template_product_expiry_alert')
            res_user_ids = self.env['res.users'].browse(res_user_ids)
            email_list = [x.email for x in res_user_ids if x.email]
            email_list_1 = ', '.join(map(str, email_list))
            company_name = self.env['res.company']._company_default_get('your.module')
            if res_user_ids and template_id and near_expiry_data_list:
                # template_id.send_mail(int(near_expiry_data_list[0]['product_id']), force_send=True)
                template_id.with_context({'company': company_name,'email_list': email_list_1, 'from_dis': True,
                                          'data_list': near_expiry_data_list}).send_mail(int(near_expiry_data_list[0]['product_id']), force_send=True)
        return True


class StockProductionLot(models.Model):
    _inherit = 'stock.production.lot'

    expiry_state = fields.Selection([('expired', 'Expired'), ('near_expired', 'Near Expired')], string="Expiry State",
                                    compute='_get_product_state')
    state_check = fields.Selection([('expired', 'Expired'), ('near_expired', 'Near Expired')], string="state")

    @api.one
    @api.constrains('alert_date', 'life_date')
    def _check_dates(self):
        if self.alert_date and self.life_date:
            if not self.alert_date <= self.life_date:
                raise ValidationError(_('Dates must be: Alert Date < Expiry Date'))

    @api.model
    def name_search(self, name, args=None, operator='=', limit=100):
        if self._context.get('default_product_id'):
            stock_production_lot_obj = self.env['stock.production.lot']
            args = args or []
            recs = self.search([('product_id', '=', self._context.get('default_product_id'))])
            if recs:
                for each_stock_lot in recs.filtered(lambda l: l.life_date).sorted(key=lambda p: (p.life_date),
                                                                                  reverse=False):
                    if each_stock_lot.expiry_state != 'expired':
                        stock_production_lot_obj |= each_stock_lot
                return stock_production_lot_obj.name_get()
        return super(StockProductionLot, self).name_search(name, args, operator, limit)

    @api.model
    def product_state_check(self):
        today_date = date.today()
        for each_stock_lot in self.filtered(lambda l: l.life_date):
            if each_stock_lot.product_id.tracking != 'none':
                life_date = datetime.strptime(str(each_stock_lot.life_date), '%Y-%m-%d %H:%M:%S').date()
                if life_date < today_date:
                    each_stock_lot.write({'state_check': 'expired'})
                else:
                    if each_stock_lot.alert_date:
                        alert_date = datetime.strptime(str(each_stock_lot.alert_date), '%Y-%m-%d %H:%M:%S').date()
                        if alert_date <= today_date:
                            each_stock_lot.write({'state_check': 'near_expired'})
            else:
                each_stock_lot.write({'state_check': ''})

    @api.one
    @api.depends('alert_date', 'life_date')
    def _get_product_state(self):
        today_date = date.today()
        for each_stock_lot in self.filtered(lambda l: l.life_date):
            if each_stock_lot.product_id.tracking != 'none':
                life_date = datetime.strptime(str(each_stock_lot.life_date), '%Y-%m-%d %H:%M:%S').date()
                if life_date < today_date:
                    each_stock_lot.expiry_state = 'expired'
                    each_stock_lot.write({'state_check': 'expired'})
                else:
                    if each_stock_lot.alert_date:
                        alert_date = datetime.strptime(str(each_stock_lot.alert_date), '%Y-%m-%d %H:%M:%S').date()
                        if alert_date <= today_date:
                            each_stock_lot.expiry_state = 'near_expired'
                            each_stock_lot.write({'state_check': 'near_expired'})
            else:
                each_stock_lot.write({'state_check': ''})


class ProductExpiryConfig(models.Model):
    _name = "product.expiry.config"
    _description = "product expiry configuration"

    name = fields.Char(string="Name", compute="_change_name", store=True)
    no_of_days = fields.Char(string="Number Of Days")
    active = fields.Boolean(string="Active")
    block_color = fields.Char(string="Block Color")
    text_color = fields.Char(string="Text Color")

    @api.model
    def create(self, vals):
        if vals.get('no_of_days') and vals.get('no_of_days').isdigit():
            vals['name'] = 'Expire In ' + vals.get('no_of_days') + ' Days'
        else:
            raise ValidationError(_('Enter only number of days'))
        return super(ProductExpiryConfig, self).create(vals)

    @api.depends('no_of_days')
    def _change_name(self):
        for each in self:
            if each.no_of_days:
                each.name = 'Expire In ' + each.no_of_days + ' Days'


class ProductExpireReport(models.Model):
    _name = 'product.expire.report'

    report_selection = fields.Selection([('product', 'Product'), ('category', 'Category'),
                                         ('warehouse', 'Warehouse'), ('location', 'Location')])

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4: