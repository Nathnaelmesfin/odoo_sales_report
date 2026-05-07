# -*- coding: utf-8 -*-

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    pos_analytics_default_date_range = fields.Selection([
        ("today", "Today"), ("yesterday", "Yesterday"), ("this_week", "This Week"),
        ("last_week", "Last Week"), ("this_month", "This Month"), ("last_month", "Last Month"),
        ("this_year", "This Year"), ("custom", "Custom Date Range"),
    ], string="Default Dashboard Date Range", default="today", config_parameter="pos_advanced_analytics.default_date_range")
    pos_analytics_auto_refresh_interval = fields.Integer(
        string="Auto-refresh Interval (seconds)", default=60,
        config_parameter="pos_advanced_analytics.auto_refresh_interval",
    )
    pos_analytics_default_pos_config_id = fields.Many2one(
        "pos.config", string="Default POS Branch",
        config_parameter="pos_advanced_analytics.default_pos_config_id",
    )
    pos_analytics_enable_target_cards = fields.Boolean(
        string="Enable Target Cards", default=True,
        config_parameter="pos_advanced_analytics.enable_target_cards",
    )
    pos_analytics_enable_waiter_analytics = fields.Boolean(
        string="Enable Waiter Analytics", default=True,
        config_parameter="pos_advanced_analytics.enable_waiter_analytics",
    )
    pos_analytics_enable_cashier_analytics = fields.Boolean(
        string="Enable Cashier Analytics", default=True,
        config_parameter="pos_advanced_analytics.enable_cashier_analytics",
    )
    pos_analytics_default_report_timezone = fields.Selection(
        [("Africa/Addis_Ababa", "Africa/Addis_Ababa")],
        string="Default Report Timezone", default="Africa/Addis_Ababa",
        config_parameter="pos_advanced_analytics.default_report_timezone",
    )
