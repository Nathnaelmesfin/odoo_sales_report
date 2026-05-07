# -*- coding: utf-8 -*-
{
    "name": "POS Advanced Analytics Dashboard",
    "version": "17.0.1.0.0",
    "category": "Point of Sale",
    "summary": "Advanced live POS sales analytics, targets, and management reports.",
    "description": """
POS Advanced Analytics Dashboard
================================
Adds a branch-ready Point of Sale analytics dashboard and reporting suite focused on
sales, orders, products, categories, waiters, cashiers, branches, payments, refunds,
discounts, taxes, peak hours, and management summaries.

This module intentionally focuses only on POS sales and operational analytics.
    """,
    "author": "Codex",
    "website": "https://www.odoo.com",
    "depends": [
        "point_of_sale",
        "pos_restaurant",
        "pos_hr",
        "web",
        "product",
        "hr",
        "account",
    ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/dashboard_actions.xml",
        "reports/pos_sales_report_action.xml",
        "reports/pos_sales_report_template.xml",
        "views/pos_analytics_report_wizard_views.xml",
        "views/pos_analytics_target_views.xml",
        "views/res_config_settings_views.xml",
        "views/pos_analytics_menu.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "pos_advanced_analytics/static/src/js/pos_analytics_service.js",
            "pos_advanced_analytics/static/src/js/pos_analytics_dashboard.js",
            "pos_advanced_analytics/static/src/xml/pos_analytics_dashboard.xml",
            "pos_advanced_analytics/static/src/scss/pos_analytics_dashboard.scss",
        ],
    },
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
