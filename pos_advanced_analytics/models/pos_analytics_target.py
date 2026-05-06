# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class PosAnalyticsTarget(models.Model):
    _name = "pos.analytics.target"
    _description = "POS Sales Analytics Target"
    _order = "date_start desc, name"

    name = fields.Char(required=True)
    date_start = fields.Date(required=True)
    date_end = fields.Date(required=True)
    pos_config_id = fields.Many2one("pos.config", string="POS Branch")
    cashier_id = fields.Many2one("res.users", string="Cashier")
    waiter_id = fields.Many2one("hr.employee", string="Waiter")
    target_amount = fields.Monetary(string="Sales Target", currency_field="currency_id")
    target_orders = fields.Integer(string="Orders Target")
    target_avg_order_value = fields.Monetary(string="Average Order Value Target", currency_field="currency_id")
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id", store=True, readonly=True)

    @api.constrains("date_start", "date_end", "target_amount", "target_orders", "target_avg_order_value")
    def _check_target_values(self):
        for target in self:
            if target.date_start and target.date_end and target.date_end < target.date_start:
                raise ValidationError(_("Target end date must be after the start date."))
            if target.target_amount < 0 or target.target_orders < 0 or target.target_avg_order_value < 0:
                raise ValidationError(_("Targets cannot be negative."))
