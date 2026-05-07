# -*- coding: utf-8 -*-

import json
from urllib.parse import quote

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError


class PosAnalyticsReportWizard(models.TransientModel):
    _name = "pos.analytics.report.wizard"
    _description = "POS Analytics Report Wizard"

    date_start = fields.Date(required=True, default=fields.Date.context_today)
    date_end = fields.Date(required=True, default=fields.Date.context_today)
    pos_config_ids = fields.Many2many("pos.config", string="POS Shops / Branches")
    cashier_ids = fields.Many2many("res.users", string="Cashiers")
    waiter_ids = fields.Many2many("hr.employee", string="Waiters")
    product_category_ids = fields.Many2many("product.category", string="Product Categories")
    product_ids = fields.Many2many("product.product", string="Products")
    payment_method_ids = fields.Many2many("pos.payment.method", string="Payment Methods")
    order_state = fields.Selection(selection="_selection_order_state", default="all", required=True)
    report_type = fields.Selection([
        ("sales_summary", "Sales Summary Report"),
        ("daily_closing", "Daily Closing Report"),
        ("product_sales", "Product Sales Report"),
        ("category_sales", "Category Sales Report"),
        ("waiter_performance", "Waiter Performance Report"),
        ("cashier_performance", "Cashier Performance Report"),
        ("branch_comparison", "Branch Comparison Report"),
        ("hourly_sales", "Hourly Sales Report"),
        ("daily_sales", "Daily Sales Report"),
        ("refund_discount", "Refund & Discount Report"),
        ("payment_method", "Payment Method Report"),
        ("tax", "Tax Report"),
        ("management_summary", "Management Summary Report"),
    ], default="management_summary", required=True)
    group_by = fields.Selection([
        ("day", "Day"), ("week", "Week"), ("month", "Month"), ("year", "Year"),
        ("product", "Product"), ("category", "Product Category"), ("cashier", "Cashier"),
        ("waiter", "Waiter"), ("branch", "POS Branch"), ("payment_method", "Payment Method"),
        ("hour", "Hour of Day"), ("weekday", "Day of Week"), ("session", "POS Session"),
    ], default="day", required=True)
    report_basis = fields.Selection([
        ("incl", "Sales Including Tax"),
        ("excl", "Sales Excluding Tax"),
        ("qty", "Quantity Sold"),
        ("net", "Net Sales After Refunds"),
    ], default="incl", required=True)
    include_raw_orders = fields.Boolean(string="Include Raw POS Orders")
    include_summary = fields.Boolean(string="Include Summary", default=True)
    export_format = fields.Selection([("pdf", "PDF"), ("xlsx", "Excel")], default="pdf", required=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, required=True)

    def _selection_order_state(self):
        selection = [("all", "All Valid Orders"), ("paid", "Paid"), ("done", "Done"), ("invoiced", "Invoiced")]
        pos_state_field = self.env["pos.order"]._fields.get("state")
        state_keys = [item[0] for item in (pos_state_field.selection if pos_state_field else [])]
        if "posted" in state_keys:
            selection.append(("posted", "Posted"))
        return selection

    @api.constrains("date_start", "date_end")
    def _check_dates(self):
        for wizard in self:
            if wizard.date_start and wizard.date_end and wizard.date_end < wizard.date_start:
                raise ValidationError(_("End date must be on or after start date."))

    def _check_analytics_access(self):
        if not self.env.user.has_group("pos_advanced_analytics.group_pos_analytics_user"):
            raise AccessError(_("You do not have access to POS analytics reports."))

    def _filters(self):
        self._check_analytics_access()
        self.ensure_one()
        states = ["paid", "done", "invoiced"] if self.order_state == "all" else [self.order_state]
        return {
            "date_range": "custom",
            "date_start": fields.Date.to_string(self.date_start),
            "date_end": fields.Date.to_string(self.date_end),
            "pos_config_ids": self.pos_config_ids.ids,
            "cashier_ids": self.cashier_ids.ids,
            "waiter_ids": self.waiter_ids.ids,
            "product_category_ids": self.product_category_ids.ids,
            "product_ids": self.product_ids.ids,
            "payment_method_ids": self.payment_method_ids.ids,
            "order_state": states,
            "report_type": self.report_type,
            "group_by": self.group_by,
            "report_basis": self.report_basis,
            "include_raw_orders": self.include_raw_orders,
            "include_summary": self.include_summary,
            "timezone": self.env["ir.config_parameter"].sudo().get_param("pos_advanced_analytics.default_report_timezone", "Africa/Addis_Ababa"),
        }

    def _report_payload(self):
        self.ensure_one()
        filters = self._filters()
        data = self.env["pos.analytics.service"].get_report_data(filters)
        data.update({
            "wizard_id": self.id,
            "report_title": dict(self._fields["report_type"].selection).get(self.report_type),
            "generated_by": self.env.user.name,
            "generated_at": fields.Datetime.context_timestamp(self, fields.Datetime.now()).strftime("%Y-%m-%d %H:%M:%S"),
            "company": self.company_id,
            "branch_filter": ", ".join(self.pos_config_ids.mapped("name")) or _("All POS Branches"),
            "group_by_label": dict(self._fields["group_by"].selection).get(self.group_by, self.group_by),
        })
        return data


    def _format_report_value(self, value):
        if isinstance(value, float):
            return "{:,.2f}".format(value)
        if isinstance(value, int):
            return "{:,}".format(value)
        if isinstance(value, list):
            return "; ".join(str(item) for item in value)
        return value or ""

    def action_generate_pdf(self):
        self.ensure_one()
        self._check_analytics_access()
        self.export_format = "pdf"
        return self.env.ref("pos_advanced_analytics.action_report_pos_analytics_pdf").report_action(self, data={"filters": self._filters()})

    def action_generate_excel(self):
        self.ensure_one()
        self._check_analytics_access()
        self.export_format = "xlsx"
        payload = quote(json.dumps(self._filters()), safe="")
        return {
            "type": "ir.actions.act_url",
            "url": "/pos_advanced_analytics/report/xlsx/%s?filters=%s" % (self.id, payload),
            "target": "self",
        }
