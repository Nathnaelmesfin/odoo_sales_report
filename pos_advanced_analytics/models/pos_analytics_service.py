# -*- coding: utf-8 -*-

from collections import defaultdict
from datetime import date, datetime, time, timedelta
import calendar
import json

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError
from odoo.tools import DEFAULT_SERVER_DATE_FORMAT, DEFAULT_SERVER_DATETIME_FORMAT


VALID_POS_STATES = ("paid", "done", "invoiced")
DEFAULT_TZ = "Africa/Addis_Ababa"


class PosAnalyticsService(models.AbstractModel):
    _name = "pos.analytics.service"
    _description = "POS Advanced Analytics Service"

    @api.model
    def get_dashboard_data(self, filters=None):
        self._check_analytics_access()
        filters = self._normalize_filters(filters or {})
        settings = self._get_settings()
        kpis = self._get_kpis(filters, settings=settings)
        dine_takeaway = self._get_dine_takeaway_sales(filters)
        data = {
            "filters": filters,
            "settings": settings,
            "basis_label": self._basis_label(filters),
            "kpis": kpis,
            "sales_trend": self._get_sales_trend(filters),
            "top_products": self._get_top_products(filters),
            "top_categories": self._get_top_categories(filters),
            "waiter_performance": self._get_waiter_performance(filters) if settings["enable_waiter_analytics"] else [],
            "cashier_performance": self._get_cashier_performance(filters) if settings["enable_cashier_analytics"] else [],
            "peak_hours": self._get_peak_hours(filters),
            "peak_days": self._get_peak_days(filters),
            "peak_hour_day_heatmap": self._get_peak_hour_day_heatmap(filters),
            "payment_methods": self._get_payment_methods(filters),
            "payment_analytics": self._get_payment_analytics(filters),
            "branch_comparison": self._get_branch_comparison(filters),
            "refund_discount_summary": self._get_refund_discount_summary(filters),
            "tax_summary": self._get_tax_summary(filters),
            "grouped_report": self.get_grouped_report_data(filters),
            "raw_orders": self._get_raw_orders(filters) if filters.get("include_raw_orders") else [],
            "target_summary": self._get_target_summary(filters) if settings["enable_target_cards"] else {},
            "daily_closing": self._get_daily_closing(filters),
            "dine_takeaway": dine_takeaway,
        }
        return data

    @api.model
    def get_dashboard_bootstrap_data(self):
        self._check_analytics_access()
        return self.get_filter_options()

    @api.model
    def get_filter_options(self):
        self._check_analytics_access()
        company_ids = self.env.companies.ids
        configs = self.env["pos.config"].search([("company_id", "in", company_ids)], order="name")
        cashiers = self.env["res.users"].search([], order="name")
        waiters = self.env["hr.employee"].search([("company_id", "in", company_ids)], order="name")
        categories = self.env["product.category"].search([], order="complete_name")
        products = self.env["product.product"].search([("sale_ok", "=", True)], order="display_name", limit=2000)
        methods = self.env["pos.payment.method"].search([("company_id", "in", company_ids + [False])], order="name")
        ICP = self.env["ir.config_parameter"].sudo()
        return {
            "date_ranges": [
                ["today", _("Today")], ["yesterday", _("Yesterday")], ["this_week", _("This Week")],
                ["last_week", _("Last Week")], ["this_month", _("This Month")], ["last_month", _("Last Month")],
                ["this_year", _("This Year")], ["custom", _("Custom Date Range")],
            ],
            "report_basis": [
                ["incl", _("Sales Including Tax")], ["excl", _("Sales Excluding Tax")],
                ["qty", _("Quantity Sold")], ["net", _("Net Sales After Refunds")],
            ],
            "pos_configs": self._name_get_payload(configs),
            "cashiers": self._name_get_payload(cashiers),
            "waiters": self._name_get_payload(waiters),
            "categories": self._name_get_payload(categories),
            "products": self._name_get_payload(products),
            "payment_methods": self._name_get_payload(methods),
            "defaults": {
                "date_range": ICP.get_param("pos_advanced_analytics.default_date_range", "today"),
                "auto_refresh_interval": int(ICP.get_param("pos_advanced_analytics.auto_refresh_interval", "60") or 60),
                "default_pos_config_id": int(ICP.get_param("pos_advanced_analytics.default_pos_config_id", "0") or 0),
                "enable_target_cards": ICP.get_param("pos_advanced_analytics.enable_target_cards", "True") == "True",
                "enable_waiter_analytics": ICP.get_param("pos_advanced_analytics.enable_waiter_analytics", "True") == "True",
                "enable_cashier_analytics": ICP.get_param("pos_advanced_analytics.enable_cashier_analytics", "True") == "True",
                "timezone": ICP.get_param("pos_advanced_analytics.default_report_timezone", DEFAULT_TZ) or DEFAULT_TZ,
            },
        }


    def _check_analytics_access(self, manager=False):
        group = "pos_advanced_analytics.group_pos_analytics_manager" if manager else "pos_advanced_analytics.group_pos_analytics_user"
        if not self.env.user.has_group(group):
            raise AccessError(_("You do not have access to POS analytics."))

    def _get_settings(self):
        ICP = self.env["ir.config_parameter"].sudo()
        interval = int(ICP.get_param("pos_advanced_analytics.auto_refresh_interval", "60") or 60)
        return {
            "date_range": ICP.get_param("pos_advanced_analytics.default_date_range", "today") or "today",
            "auto_refresh_interval": max(interval, 30),
            "default_pos_config_id": int(ICP.get_param("pos_advanced_analytics.default_pos_config_id", "0") or 0),
            "enable_target_cards": ICP.get_param("pos_advanced_analytics.enable_target_cards", "True") == "True",
            "enable_waiter_analytics": ICP.get_param("pos_advanced_analytics.enable_waiter_analytics", "True") == "True",
            "enable_cashier_analytics": ICP.get_param("pos_advanced_analytics.enable_cashier_analytics", "True") == "True",
            "timezone": ICP.get_param("pos_advanced_analytics.default_report_timezone", DEFAULT_TZ) or DEFAULT_TZ,
        }

    def _basis_label(self, filters):
        return dict([
            ("incl", _("Sales Including Tax")),
            ("excl", _("Sales Excluding Tax")),
            ("qty", _("Quantity Sold")),
            ("net", _("Net Sales After Refunds")),
        ]).get(filters.get("report_basis"), _("Sales Including Tax"))

    def _basis_metric_name(self, filters):
        return dict([
            ("incl", "sales_including_tax"),
            ("excl", "sales_excluding_tax"),
            ("qty", "quantity_sold"),
            ("net", "net_sales_after_refunds"),
        ]).get(filters.get("report_basis"), "sales_including_tax")

    def _name_get_payload(self, records):
        return [{"id": rec.id, "name": rec.display_name} for rec in records]

    def _normalize_filters(self, filters):
        ICP = self.env["ir.config_parameter"].sudo()
        tz = filters.get("timezone") or ICP.get_param("pos_advanced_analytics.default_report_timezone", DEFAULT_TZ) or DEFAULT_TZ
        if tz not in pytz.all_timezones:
            tz = DEFAULT_TZ
        date_range = filters.get("date_range") or ICP.get_param("pos_advanced_analytics.default_date_range", "today") or "today"
        start_date, end_date = self._date_range_to_dates(date_range, filters.get("date_start"), filters.get("date_end"), tz)
        return {
            "date_range": date_range,
            "date_start": fields.Date.to_string(start_date),
            "date_end": fields.Date.to_string(end_date),
            "timezone": tz,
            "pos_config_ids": self._as_int_list(filters.get("pos_config_ids") or filters.get("pos_config_id")),
            "cashier_ids": self._as_int_list(filters.get("cashier_ids") or filters.get("cashier_id")),
            "waiter_ids": self._as_int_list(filters.get("waiter_ids") or filters.get("waiter_id")),
            "product_category_ids": self._as_int_list(filters.get("product_category_ids") or filters.get("product_category_id")),
            "product_ids": self._as_int_list(filters.get("product_ids") or filters.get("product_id")),
            "payment_method_ids": self._as_int_list(filters.get("payment_method_ids") or filters.get("payment_method_id")),
            "report_basis": filters.get("report_basis") or "incl",
            "group_by": filters.get("group_by") or "day",
            "report_type": filters.get("report_type") or "sales_summary",
            "include_raw_orders": bool(filters.get("include_raw_orders")),
            "include_summary": filters.get("include_summary", True),
            "order_state": self._valid_states(filters.get("order_state")),
            "company_ids": self.env.companies.ids,
        }

    def _date_range_to_dates(self, date_range, start, end, tz):
        today = fields.Date.context_today(self.with_context(tz=tz))
        if date_range == "yesterday":
            return today - timedelta(days=1), today - timedelta(days=1)
        if date_range == "this_week":
            return today - timedelta(days=today.weekday()), today + timedelta(days=6 - today.weekday())
        if date_range == "last_week":
            this_start = today - timedelta(days=today.weekday())
            return this_start - timedelta(days=7), this_start - timedelta(days=1)
        if date_range == "this_month":
            return today.replace(day=1), today.replace(day=calendar.monthrange(today.year, today.month)[1])
        if date_range == "last_month":
            first = today.replace(day=1)
            last_month = first - timedelta(days=1)
            return last_month.replace(day=1), last_month
        if date_range == "this_year":
            return date(today.year, 1, 1), date(today.year, 12, 31)
        if date_range == "custom" and start and end:
            return fields.Date.to_date(start), fields.Date.to_date(end)
        return today, today

    def _as_int_list(self, value):
        if not value:
            return []
        if isinstance(value, int):
            return [value]
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except Exception:
                value = [value]
        return [int(v) for v in value if v]

    def _valid_states(self, states=None):
        valid_states = list(VALID_POS_STATES)
        pos_state_field = self.env["pos.order"]._fields.get("state")
        state_keys = [item[0] for item in (pos_state_field.selection if pos_state_field else [])]
        if "posted" in state_keys:
            valid_states.append("posted")
        states = self._as_str_list(states) or list(VALID_POS_STATES)
        return [state for state in states if state in valid_states] or list(VALID_POS_STATES)

    def _as_str_list(self, value):
        if not value:
            return []
        if isinstance(value, str):
            return [value]
        return [str(v) for v in value if v]

    def _local_bounds_utc(self, filters):
        tz = filters.get("timezone") or DEFAULT_TZ
        date_start = fields.Date.to_date(filters["date_start"])
        date_end = fields.Date.to_date(filters["date_end"])
        start_dt = datetime.combine(date_start, time.min)
        end_dt = datetime.combine(date_end, time.max.replace(microsecond=0))
        start_utc = fields.Datetime.context_timestamp(self.with_context(tz=tz), start_dt).replace(tzinfo=None)
        end_utc = fields.Datetime.context_timestamp(self.with_context(tz=tz), end_dt).replace(tzinfo=None)
        # context_timestamp converts UTC to local; reverse using Python timezone support via Odoo fields is not exposed.
        # PostgreSQL filtering below applies local timezone conversion, so these broad UTC bounds are intentionally unused.
        return start_utc, end_utc

    def _order_where(self, filters, alias="po", include_payment=False):
        clauses = [
            f"{alias}.state = ANY(%s)",
            f"{alias}.company_id = ANY(%s)",
            f"(({alias}.date_order AT TIME ZONE 'UTC' AT TIME ZONE %s)::date BETWEEN %s AND %s)",
        ]
        params = [filters["order_state"], filters["company_ids"], filters["timezone"], filters["date_start"], filters["date_end"]]
        if filters.get("pos_config_ids"):
            clauses.append(f"{alias}.config_id = ANY(%s)")
            params.append(filters["pos_config_ids"])
        if filters.get("cashier_ids"):
            clauses.append(f"{alias}.user_id = ANY(%s)")
            params.append(filters["cashier_ids"])
        if filters.get("waiter_ids"):
            clauses.append(f"{alias}.employee_id = ANY(%s)")
            params.append(filters["waiter_ids"])
        if filters.get("product_ids"):
            clauses.append(f"EXISTS (SELECT 1 FROM pos_order_line polx WHERE polx.order_id = {alias}.id AND polx.product_id = ANY(%s))")
            params.append(filters["product_ids"])
        if filters.get("product_category_ids"):
            clauses.append(
                f"EXISTS (SELECT 1 FROM pos_order_line polc JOIN product_product ppc ON ppc.id = polc.product_id "
                f"JOIN product_template ptc ON ptc.id = ppc.product_tmpl_id WHERE polc.order_id = {alias}.id AND ptc.categ_id = ANY(%s))"
            )
            params.append(filters["product_category_ids"])
        if filters.get("payment_method_ids"):
            clauses.append(f"EXISTS (SELECT 1 FROM pos_payment ppay WHERE ppay.pos_order_id = {alias}.id AND ppay.payment_method_id = ANY(%s))")
            params.append(filters["payment_method_ids"])
        return " AND ".join(clauses), params

    def _line_where(self, filters):
        where, params = self._order_where(filters, alias="po")
        if filters.get("product_ids"):
            where += " AND pol.product_id = ANY(%s)"
            params.append(filters["product_ids"])
        if filters.get("product_category_ids"):
            where += " AND pt.categ_id = ANY(%s)"
            params.append(filters["product_category_ids"])
        return where, params

    def _amount_expr(self, filters, prefix=""):
        basis = filters.get("report_basis")
        if basis == "excl":
            return f"{prefix}price_subtotal"
        if basis == "qty":
            return f"{prefix}qty"
        return f"{prefix}price_subtotal_incl"

    def _get_basis_order_metric(self, filters):
        where, params = self._order_where(filters, alias="po")
        basis = filters.get("report_basis")
        if basis == "qty":
            line_where, line_params = self._line_where(filters)
            row = self._fetchone_dict(f"""
                SELECT COALESCE(SUM(pol.qty), 0) AS value
                FROM pos_order_line pol
                JOIN pos_order po ON po.id = pol.order_id
                JOIN product_product pp ON pp.id = pol.product_id
                JOIN product_template pt ON pt.id = pp.product_tmpl_id
                WHERE {line_where}
            """, line_params)
            return float(row.get("value") or 0.0)
        if basis == "excl":
            expr = "po.amount_total - po.amount_tax"
        elif basis == "net":
            expr = "po.amount_total"
        else:
            expr = "po.amount_total"
        row = self._fetchone_dict(f"SELECT COALESCE(SUM({expr}), 0) AS value FROM pos_order po WHERE {where}", params)
        return float(row.get("value") or 0.0)

    def _order_basis_expr(self, filters, alias="po"):
        basis = filters.get("report_basis")
        if basis == "qty":
            return f"(SELECT COALESCE(SUM(pol_basis_qty.qty), 0) FROM pos_order_line pol_basis_qty WHERE pol_basis_qty.order_id = {alias}.id)"
        if basis == "excl":
            return f"({alias}.amount_total - {alias}.amount_tax)"
        if basis == "net":
            return f"{alias}.amount_total"
        return f"{alias}.amount_total"

    def _line_basis_expr(self, filters, alias="pol"):
        basis = filters.get("report_basis")
        if basis == "excl":
            return f"{alias}.price_subtotal"
        if basis == "qty":
            return f"{alias}.qty"
        return f"{alias}.price_subtotal_incl"

    def _fetchall_dict(self, query, params):
        self.env.cr.execute(query, params)
        return [dict(row) for row in self.env.cr.dictfetchall()]

    def _fetchone_dict(self, query, params):
        self.env.cr.execute(query, params)
        return dict(self.env.cr.dictfetchone() or {})

    def _get_kpis(self, filters, settings=None):
        settings = settings or self._get_settings()
        where, params = self._order_where(filters, alias="po")
        metric_expr = self._order_basis_expr(filters, "po")
        order_row = self._fetchone_dict(f"""
            SELECT
                COALESCE(SUM(CASE WHEN po.amount_total >= 0 THEN {metric_expr} ELSE 0 END), 0) AS total_sales,
                COALESCE(SUM(po.amount_total), 0) AS net_sales,
                COUNT(po.id) AS total_orders,
                COALESCE(SUM(ABS(CASE WHEN po.amount_total < 0 THEN po.amount_total ELSE 0 END)), 0) AS total_refunds,
                COALESCE(SUM(po.amount_tax), 0) AS total_tax
            FROM pos_order po
            WHERE {where}
        """, params)
        line_where, line_params = self._line_where(filters)
        line_row = self._fetchone_dict(f"""
            SELECT
                COALESCE(SUM(pol.qty), 0) AS total_qty,
                COALESCE(SUM(ABS(pol.qty) * pol.price_unit * pol.discount / 100.0), 0) AS total_discounts
            FROM pos_order_line pol
            JOIN pos_order po ON po.id = pol.order_id
            JOIN product_product pp ON pp.id = pol.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            WHERE {line_where}
        """, line_params)
        payment_rows = self._payment_group_rows(filters)
        cash_sales = sum(r["amount"] for r in payment_rows if r["method_type"] == "cash")
        bank_sales = sum(r["amount"] for r in payment_rows if r["method_type"] == "bank")
        mobile_sales = sum(r["amount"] for r in payment_rows if r["method_type"] == "mobile")
        best_product = (self._get_top_products(filters, limit=1) or [{}])[0]
        best_category = (self._get_top_categories(filters, limit=1) or [{}])[0]
        top_waiter = (self._get_waiter_performance(filters, limit=1) or [{}])[0] if settings["enable_waiter_analytics"] else {}
        top_cashier = (self._get_cashier_performance(filters, limit=1) or [{}])[0] if settings["enable_cashier_analytics"] else {}
        peak_hour = (self._get_peak_hours(filters, limit=1) or [{}])[0]
        peak_day = (self._get_peak_days(filters, limit=1) or [{}])[0]
        branch_rows = self._get_branch_comparison(filters)
        dine_takeaway = self._get_dine_takeaway_sales(filters)
        total_orders = order_row.get("total_orders") or 0
        basis_metric = self._get_basis_order_metric(filters)
        total_sales = basis_metric
        return {
            "basis_label": self._basis_label(filters),
            "basis_metric_name": self._basis_metric_name(filters),
            "basis_metric": basis_metric,
            "total_sales": total_sales,
            "net_sales": float(order_row.get("net_sales") or 0.0),
            "total_orders": total_orders,
            "average_order_value": total_sales / total_orders if total_orders else 0.0,
            "total_quantity_sold": float(line_row.get("total_qty") or 0.0),
            "total_discounts": float(line_row.get("total_discounts") or 0.0),
            "total_refunds": float(order_row.get("total_refunds") or 0.0),
            "total_tax": float(order_row.get("total_tax") or 0.0),
            "cash_sales": cash_sales,
            "bank_card_sales": bank_sales,
            "mobile_money_sales": mobile_sales,
            "best_selling_product": best_product.get("product_name") or _("No sales"),
            "best_selling_category": best_category.get("category_name") or _("No sales"),
            "top_waiter": top_waiter.get("waiter_name") or _("No waiter"),
            "top_cashier": top_cashier.get("cashier_name") or _("No cashier"),
            "peak_sales_hour": peak_hour.get("label") or _("No data"),
            "peak_sales_day": peak_day.get("label") or _("No data"),
            "dine_takeaway_available": dine_takeaway.get("available", False),
            "dine_in_sales": dine_takeaway.get("dine_in_sales", 0.0),
            "takeaway_sales": dine_takeaway.get("takeaway_sales", 0.0),
            "branch_sales_comparison_summary": self._branch_summary_text(branch_rows),
            "sales_per_hour": sum(r.get("sales_amount", 0.0) for r in self._get_peak_hours(filters)) / 24.0,
            "sales_per_waiter": self._average_metric(self._get_waiter_performance(filters), "total_sales") if settings["enable_waiter_analytics"] else 0.0,
            "sales_per_cashier": self._average_metric(self._get_cashier_performance(filters), "total_collected") if settings["enable_cashier_analytics"] else 0.0,
        }

    def _average_metric(self, rows, key):
        return sum(r.get(key, 0.0) for r in rows) / len(rows) if rows else 0.0

    def _branch_summary_text(self, rows):
        if not rows:
            return _("No branch sales in selected period")
        top = max(rows, key=lambda r: r.get("total_sales", 0.0))
        return _("%s leads with %s sales across %s branch(es)") % (top.get("branch_name"), round(top.get("total_sales", 0.0), 2), len(rows))

    def _get_sales_trend(self, filters):
        group = filters.get("group_by") if filters.get("group_by") in ("day", "week", "month", "year") else "day"
        date_expr = self._trend_date_expr(group, filters["timezone"])
        where, params = self._order_where(filters, alias="po")
        metric_expr = self._order_basis_expr(filters, "po")
        rows = self._fetchall_dict(f"""
            SELECT {date_expr} AS period_key,
                   COALESCE(SUM(CASE WHEN po.amount_total >= 0 THEN {metric_expr} ELSE 0 END), 0) AS total_sales,
                   COALESCE(SUM({metric_expr}), 0) AS basis_amount,
                   COALESCE(SUM(po.amount_total), 0) AS net_sales,
                   COUNT(po.id) AS order_count,
                   COALESCE(SUM(po.amount_tax), 0) AS tax_amount
            FROM pos_order po
            WHERE {where}
            GROUP BY 1
            ORDER BY 1
        """, params)
        return [{"label": str(r["period_key"]), **r} for r in rows]

    def _trend_date_expr(self, group, tz):
        base = f"(po.date_order AT TIME ZONE 'UTC' AT TIME ZONE '{tz}')"
        if group == "week":
            return f"TO_CHAR(date_trunc('week', {base}), 'IYYY-IW')"
        if group == "month":
            return f"TO_CHAR(date_trunc('month', {base}), 'YYYY-MM')"
        if group == "year":
            return f"TO_CHAR(date_trunc('year', {base}), 'YYYY')"
        return f"TO_CHAR({base}::date, 'YYYY-MM-DD')"

    def _get_top_products(self, filters, limit=20):
        where, params = self._line_where(filters)
        basis_expr = self._line_basis_expr(filters, "pol")
        rows = self._fetchall_dict(f"""
            SELECT pol.product_id,
                   COALESCE(pt.name->>%s, pt.name->>'en_US', pp.default_code, 'Product') AS product_name,
                   COALESCE(pc.complete_name, pc.name, 'No Category') AS category_name,
                   COALESCE(SUM(pol.qty), 0) AS quantity_sold,
                   COALESCE(SUM(CASE WHEN pol.qty >= 0 THEN pol.price_subtotal_incl ELSE 0 END), 0) AS gross_sales,
                   COALESCE(SUM(pol.price_subtotal_incl), 0) AS net_sales,
                   COALESCE(SUM({basis_expr}), 0) AS basis_amount,
                   COALESCE(SUM(CASE WHEN pol.qty < 0 THEN ABS(pol.qty) ELSE 0 END), 0) AS refund_quantity,
                   COALESCE(SUM(CASE WHEN pol.price_subtotal_incl < 0 THEN ABS(pol.price_subtotal_incl) ELSE 0 END), 0) AS refund_amount,
                   COALESCE(SUM(ABS(pol.qty) * pol.price_unit * pol.discount / 100.0), 0) AS discount_amount,
                   CASE WHEN SUM(ABS(pol.qty)) <> 0 THEN COALESCE(SUM(pol.price_subtotal_incl), 0) / SUM(ABS(pol.qty)) ELSE 0 END AS average_unit_price
            FROM pos_order_line pol
            JOIN pos_order po ON po.id = pol.order_id
            JOIN product_product pp ON pp.id = pol.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            LEFT JOIN product_category pc ON pc.id = pt.categ_id
            WHERE {where}
            GROUP BY pol.product_id, product_name, category_name
            ORDER BY basis_amount DESC, quantity_sold DESC
            LIMIT %s
        """, [self.env.lang or "en_US"] + params + [limit])
        return rows

    def _get_top_categories(self, filters, limit=20):
        where, params = self._line_where(filters)
        basis_expr = self._line_basis_expr(filters, "pol")
        rows = self._fetchall_dict(f"""
            SELECT pt.categ_id AS category_id,
                   COALESCE(pc.complete_name, pc.name, 'No Category') AS category_name,
                   COALESCE(SUM(pol.qty), 0) AS quantity_sold,
                   COALESCE(SUM(CASE WHEN pol.qty >= 0 THEN pol.price_subtotal_incl ELSE 0 END), 0) AS gross_sales,
                   COALESCE(SUM(pol.price_subtotal_incl), 0) AS net_sales,
                   COALESCE(SUM({basis_expr}), 0) AS basis_amount,
                   COALESCE(SUM(CASE WHEN pol.qty < 0 THEN ABS(pol.qty) ELSE 0 END), 0) AS refund_quantity,
                   COALESCE(SUM(CASE WHEN pol.price_subtotal_incl < 0 THEN ABS(pol.price_subtotal_incl) ELSE 0 END), 0) AS refund_amount,
                   COALESCE(SUM(ABS(pol.qty) * pol.price_unit * pol.discount / 100.0), 0) AS discount_amount,
                   COUNT(DISTINCT pol.product_id) AS product_count
            FROM pos_order_line pol
            JOIN pos_order po ON po.id = pol.order_id
            JOIN product_product pp ON pp.id = pol.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            LEFT JOIN product_category pc ON pc.id = pt.categ_id
            WHERE {where}
            GROUP BY pt.categ_id, category_name
            ORDER BY basis_amount DESC, quantity_sold DESC
            LIMIT %s
        """, params + [limit])
        return rows

    def _get_waiter_performance(self, filters, limit=50):
        where, params = self._line_where(filters)
        basis_expr = self._line_basis_expr(filters, "pol")
        rows = self._fetchall_dict(f"""
            SELECT po.employee_id AS waiter_id,
                   COALESCE(he.name, 'No Waiter') AS waiter_name,
                   COALESCE(SUM({basis_expr}), 0) AS total_sales,
                   COUNT(DISTINCT po.id) AS total_orders,
                   COALESCE(SUM(pol.qty), 0) AS quantity_sold,
                   COALESCE(SUM(CASE WHEN pol.price_subtotal_incl < 0 THEN ABS(pol.price_subtotal_incl) ELSE 0 END), 0) AS refunds,
                   COALESCE(SUM(ABS(pol.qty) * pol.price_unit * pol.discount / 100.0), 0) AS discounts
            FROM pos_order_line pol
            JOIN pos_order po ON po.id = pol.order_id
            JOIN product_product pp ON pp.id = pol.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            LEFT JOIN hr_employee he ON he.id = po.employee_id
            WHERE {where}
            GROUP BY po.employee_id, waiter_name
            ORDER BY total_sales DESC
            LIMIT %s
        """, params + [limit])
        for row in rows:
            row["average_order_value"] = row["total_sales"] / row["total_orders"] if row["total_orders"] else 0.0
        return rows

    def _get_cashier_performance(self, filters, limit=50):
        where, params = self._order_where(filters, alias="po")
        basis_expr = self._order_basis_expr(filters, "po")
        rows = self._fetchall_dict(f"""
            WITH filtered_orders AS (
                SELECT po.id, po.user_id, po.amount_paid, po.amount_total, {basis_expr} AS basis_amount
                FROM pos_order po
                WHERE {where}
            ), discount_by_cashier AS (
                SELECT fo.user_id, COALESCE(SUM(ABS(pol.qty) * pol.price_unit * pol.discount / 100.0), 0) AS discounts
                FROM filtered_orders fo
                JOIN pos_order_line pol ON pol.order_id = fo.id
                GROUP BY fo.user_id
            )
            SELECT fo.user_id AS cashier_id,
                   COALESCE(rp.name, ru.login, 'No Cashier') AS cashier_name,
                   COALESCE(SUM(fo.amount_paid), 0) AS total_collected,
                   COALESCE(SUM(fo.basis_amount), 0) AS total_sales,
                   COUNT(fo.id) AS number_of_orders,
                   COALESCE(SUM(CASE WHEN fo.amount_total < 0 THEN ABS(fo.amount_total) ELSE 0 END), 0) AS refunds,
                   COALESCE(MAX(dbc.discounts), 0) AS discounts
            FROM filtered_orders fo
            LEFT JOIN res_users ru ON ru.id = fo.user_id
            LEFT JOIN res_partner rp ON rp.id = ru.partner_id
            LEFT JOIN discount_by_cashier dbc ON dbc.user_id IS NOT DISTINCT FROM fo.user_id
            GROUP BY fo.user_id, cashier_name
            ORDER BY total_sales DESC, total_collected DESC
            LIMIT %s
        """, params + [limit])
        breakdown = self._cashier_payment_breakdown(filters)
        for row in rows:
            row["average_ticket_size"] = row["total_collected"] / row["number_of_orders"] if row["number_of_orders"] else 0.0
            row["payment_method_breakdown"] = breakdown.get(row["cashier_id"] or 0, [])
        return rows

    def _get_peak_hours(self, filters, limit=None):
        where, params = self._order_where(filters, alias="po")
        metric_expr = self._order_basis_expr(filters, "po")
        limit_sql = " LIMIT %s" if limit else ""
        rows = self._fetchall_dict(f"""
            SELECT EXTRACT(HOUR FROM (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %s))::int AS hour,
                   COUNT(po.id) AS order_count,
                   COALESCE(SUM({metric_expr}), 0) AS sales_amount,
                   COALESCE(SUM(po.amount_total), 0) AS net_sales
            FROM pos_order po
            WHERE {where}
            GROUP BY 1
            ORDER BY sales_amount DESC, order_count DESC
            {limit_sql}
        """, [filters["timezone"]] + params + ([limit] if limit else []))
        for row in rows:
            row["label"] = "%02d:00" % row["hour"]
            row["average_order_value"] = row["sales_amount"] / row["order_count"] if row["order_count"] else 0.0
        return rows

    def _get_peak_days(self, filters, limit=None):
        where, params = self._order_where(filters, alias="po")
        metric_expr = self._order_basis_expr(filters, "po")
        limit_sql = " LIMIT %s" if limit else ""
        rows = self._fetchall_dict(f"""
            SELECT EXTRACT(ISODOW FROM (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %s))::int AS day_number,
                   COUNT(po.id) AS order_count,
                   COALESCE(SUM({metric_expr}), 0) AS sales_amount,
                   COALESCE(SUM(po.amount_total), 0) AS net_sales
            FROM pos_order po
            WHERE {where}
            GROUP BY 1
            ORDER BY sales_amount DESC, order_count DESC
            {limit_sql}
        """, [filters["timezone"]] + params + ([limit] if limit else []))
        for row in rows:
            row["label"] = calendar.day_name[row["day_number"] - 1]
            row["average_order_value"] = row["sales_amount"] / row["order_count"] if row["order_count"] else 0.0
        return rows

    def _payment_group_rows(self, filters):
        where, params = self._order_where(filters, alias="po")
        if filters.get("payment_method_ids"):
            where += " AND pp.payment_method_id = ANY(%s)"
            params.append(filters["payment_method_ids"])
        rows = self._fetchall_dict(f"""
            SELECT ppm.id AS payment_method_id,
                   ppm.name AS payment_method_name,
                   COALESCE(ppm.journal_id, 0) AS journal_id,
                   COALESCE(SUM(pp.amount), 0) AS amount,
                   COUNT(DISTINCT po.id) AS order_count
            FROM pos_payment pp
            JOIN pos_order po ON po.id = pp.pos_order_id
            JOIN pos_payment_method ppm ON ppm.id = pp.payment_method_id
            WHERE {where}
            GROUP BY ppm.id, ppm.name, ppm.journal_id
            ORDER BY amount DESC
        """, params)
        journal_ids = [r["journal_id"] for r in rows if r.get("journal_id")]
        journal_types = {j.id: j.type for j in self.env["account.journal"].browse(journal_ids)}
        for row in rows:
            row["method_type"] = self._classify_payment(row["payment_method_name"], journal_types.get(row.get("journal_id")))
        return rows

    def _classify_payment(self, name, journal_type=None):
        lower = (name or "").lower()
        if journal_type == "cash" or "cash" in lower:
            return "cash"
        if any(token in lower for token in ("mobile", "momo", "telebirr", "mpesa", "wallet")):
            return "mobile"
        if journal_type == "bank" or any(token in lower for token in ("card", "bank", "visa", "master")):
            return "bank"
        return "other"

    def _get_payment_methods(self, filters):
        rows = self._payment_group_rows(filters)
        total = sum(row.get("amount", 0.0) for row in rows) or 0.0
        for row in rows:
            row["percentage"] = row.get("amount", 0.0) / total * 100.0 if total else 0.0
        return rows

    def _cashier_payment_breakdown(self, filters):
        where, params = self._order_where(filters, alias="po")
        rows = self._fetchall_dict(f"""
            SELECT COALESCE(po.user_id, 0) AS cashier_id,
                   ppm.name AS payment_method_name,
                   COALESCE(SUM(pp.amount), 0) AS amount
            FROM pos_payment pp
            JOIN pos_order po ON po.id = pp.pos_order_id
            JOIN pos_payment_method ppm ON ppm.id = pp.payment_method_id
            WHERE {where}
            GROUP BY COALESCE(po.user_id, 0), ppm.name
            ORDER BY amount DESC
        """, params)
        grouped = defaultdict(list)
        for row in rows:
            grouped[row["cashier_id"]].append(row)
        return grouped

    def _get_branch_comparison(self, filters):
        where, params = self._order_where(filters, alias="po")
        metric_expr = self._order_basis_expr(filters, "po")
        rows = self._fetchall_dict(f"""
            SELECT po.config_id AS branch_id,
                   pc.name AS branch_name,
                   COALESCE(SUM(CASE WHEN po.amount_total >= 0 THEN {metric_expr} ELSE 0 END), 0) AS total_sales,
                   COALESCE(SUM(po.amount_total), 0) AS net_sales,
                   COUNT(po.id) AS total_orders,
                   EXTRACT(HOUR FROM (MAX(po.date_order) AT TIME ZONE 'UTC' AT TIME ZONE %s))::int AS sample_hour
            FROM pos_order po
            JOIN pos_config pc ON pc.id = po.config_id
            WHERE {where}
            GROUP BY po.config_id, pc.name
            ORDER BY total_sales DESC
        """, [filters["timezone"]] + params)
        for row in rows:
            branch_filter = dict(filters, pos_config_ids=[row["branch_id"]])
            row["average_order_value"] = row["total_sales"] / row["total_orders"] if row["total_orders"] else 0.0
            row["top_product"] = (self._get_top_products(branch_filter, 1) or [{}])[0].get("product_name", "")
            row["top_category"] = (self._get_top_categories(branch_filter, 1) or [{}])[0].get("category_name", "")
            row["peak_hour"] = (self._get_peak_hours(branch_filter, 1) or [{}])[0].get("label", "")
            row["peak_day"] = (self._get_peak_days(branch_filter, 1) or [{}])[0].get("label", "")
            row["payment_method_breakdown"] = self._payment_breakdown(branch_filter, "branch")
        return rows

    def _get_refund_discount_summary(self, filters):
        where, params = self._line_where(filters)
        row = self._fetchone_dict(f"""
            SELECT COALESCE(SUM(CASE WHEN pol.price_subtotal_incl < 0 THEN ABS(pol.price_subtotal_incl) ELSE 0 END), 0) AS total_refund_amount,
                   COUNT(DISTINCT CASE WHEN pol.price_subtotal_incl < 0 OR po.amount_total < 0 THEN po.id END) AS refund_order_count,
                   COALESCE(SUM(CASE WHEN pol.qty < 0 THEN ABS(pol.qty) ELSE 0 END), 0) AS refund_quantity,
                   COALESCE(SUM(ABS(pol.qty) * pol.price_unit * pol.discount / 100.0), 0) AS discount_amount,
                   COUNT(DISTINCT CASE WHEN pol.discount > 0 THEN po.id END) AS discounted_order_count
            FROM pos_order_line pol
            JOIN pos_order po ON po.id = pol.order_id
            JOIN product_product pp ON pp.id = pol.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            WHERE {where}
        """, params)
        for group in ("cashier", "waiter", "product", "category", "branch", "date"):
            row["discount_by_%s" % group] = self._discount_by(filters, group)
            row["refund_by_%s" % group] = self._refund_by(filters, group)
        return row

    def _refund_by(self, filters, group):
        where, params = self._line_where(filters)
        joins = ""
        extra_params = []
        if group == "cashier":
            select = "po.user_id AS id, COALESCE(rp.name, ru.login, 'No Cashier') AS name"
            joins = "LEFT JOIN res_users ru ON ru.id = po.user_id LEFT JOIN res_partner rp ON rp.id = ru.partner_id"
            groupby = "po.user_id, name"
        elif group == "waiter":
            select = "po.employee_id AS id, COALESCE(he.name, 'No Waiter') AS name"
            joins = "LEFT JOIN hr_employee he ON he.id = po.employee_id"
            groupby = "po.employee_id, name"
        elif group == "category":
            select = "pt.categ_id AS id, COALESCE(pc.complete_name, pc.name, 'No Category') AS name"
            joins = "LEFT JOIN product_category pc ON pc.id = pt.categ_id"
            groupby = "pt.categ_id, name"
        elif group == "branch":
            select = "po.config_id AS id, COALESCE(pconf.name, 'No Branch') AS name"
            joins = "LEFT JOIN pos_config pconf ON pconf.id = po.config_id"
            groupby = "po.config_id, name"
        elif group == "date":
            select = "0 AS id, TO_CHAR((po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %s)::date, 'YYYY-MM-DD') AS name"
            extra_params = [filters["timezone"]]
            groupby = "name"
        else:
            select = "pol.product_id AS id, COALESCE(pt.name->>%s, pt.name->>'en_US', 'Product') AS name"
            extra_params = [self.env.lang or "en_US"]
            groupby = "pol.product_id, name"
        return self._fetchall_dict(f"""
            SELECT {select},
                   COALESCE(SUM(CASE WHEN pol.price_subtotal_incl < 0 THEN ABS(pol.price_subtotal_incl) ELSE 0 END), 0) AS refund_amount,
                   COALESCE(SUM(CASE WHEN pol.qty < 0 THEN ABS(pol.qty) ELSE 0 END), 0) AS refund_quantity,
                   COUNT(DISTINCT po.id) AS order_count
            FROM pos_order_line pol
            JOIN pos_order po ON po.id = pol.order_id
            JOIN product_product pp ON pp.id = pol.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            {joins}
            WHERE {where} AND (pol.price_subtotal_incl < 0 OR pol.qty < 0 OR po.amount_total < 0)
            GROUP BY {groupby}
            ORDER BY refund_amount DESC
            LIMIT 50
        """, extra_params + params)

    def _discount_by(self, filters, group):
        where, params = self._line_where(filters)
        if group == "cashier":
            select = "po.user_id AS id, COALESCE(rp.name, ru.login, 'No Cashier') AS name"
            joins = "LEFT JOIN res_users ru ON ru.id = po.user_id LEFT JOIN res_partner rp ON rp.id = ru.partner_id"
            groupby = "po.user_id, name"
        elif group == "waiter":
            select = "po.employee_id AS id, COALESCE(he.name, 'No Waiter') AS name"
            joins = "LEFT JOIN hr_employee he ON he.id = po.employee_id"
            groupby = "po.employee_id, name"
        elif group == "category":
            select = "pt.categ_id AS id, COALESCE(pc.complete_name, pc.name, 'No Category') AS name"
            joins = "LEFT JOIN product_category pc ON pc.id = pt.categ_id"
            groupby = "pt.categ_id, name"
        elif group == "branch":
            select = "po.config_id AS id, COALESCE(pconf.name, 'No Branch') AS name"
            joins = "LEFT JOIN pos_config pconf ON pconf.id = po.config_id"
            groupby = "po.config_id, name"
        elif group == "date":
            select = "0 AS id, TO_CHAR((po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %s)::date, 'YYYY-MM-DD') AS name"
            joins = ""
            groupby = "name"
            params = [filters["timezone"]] + params
        else:
            select = "pol.product_id AS id, COALESCE(pt.name->>%s, pt.name->>'en_US', 'Product') AS name"
            joins = ""
            groupby = "pol.product_id, name"
            params = [self.env.lang or "en_US"] + params
        return self._fetchall_dict(f"""
            SELECT {select}, COALESCE(SUM(ABS(pol.qty) * pol.price_unit * pol.discount / 100.0), 0) AS discount_amount
            FROM pos_order_line pol
            JOIN pos_order po ON po.id = pol.order_id
            JOIN product_product pp ON pp.id = pol.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            {joins}
            WHERE {where} AND pol.discount > 0
            GROUP BY {groupby}
            ORDER BY discount_amount DESC
            LIMIT 20
        """, params)

    def _get_tax_summary(self, filters):
        where, params = self._order_where(filters, alias="po")
        return self._fetchall_dict(f"""
            SELECT COALESCE(pc.name, 'No Branch') AS branch_name,
                   COALESCE(SUM(po.amount_tax), 0) AS tax_amount,
                   COUNT(po.id) AS order_count
            FROM pos_order po
            LEFT JOIN pos_config pc ON pc.id = po.config_id
            WHERE {where}
            GROUP BY pc.name
            ORDER BY tax_amount DESC
        """, params)

    def _get_dine_takeaway_sales(self, filters):
        where, params = self._order_where(filters, alias="po")
        metric_expr = self._order_basis_expr(filters, "po")
        columns = self._table_columns("pos_order")
        if "takeaway" in columns:
            row = self._fetchone_dict(f"""
                SELECT COALESCE(SUM(CASE WHEN po.takeaway THEN {metric_expr} ELSE 0 END), 0) AS takeaway_sales,
                       COALESCE(SUM(CASE WHEN NOT po.takeaway THEN {metric_expr} ELSE 0 END), 0) AS dine_in_sales,
                       COUNT(po.id) AS order_count
                FROM pos_order po WHERE {where}
            """, params)
            row.update({"available": True, "source": "takeaway"})
            return row
        restaurant_markers = [field for field in ("table_id", "floor_id") if field in columns]
        if "table_id" in columns:
            row = self._fetchone_dict(f"""
                SELECT COALESCE(SUM(CASE WHEN po.table_id IS NOT NULL THEN {metric_expr} ELSE 0 END), 0) AS dine_in_sales,
                       COALESCE(SUM(CASE WHEN po.table_id IS NULL THEN {metric_expr} ELSE 0 END), 0) AS takeaway_sales,
                       COUNT(po.id) AS order_count
                FROM pos_order po WHERE {where}
            """, params)
            row.update({"available": True, "source": "table_id_inference"})
            return row
        return {"available": False, "source": "unavailable", "dine_in_sales": 0.0, "takeaway_sales": 0.0, "order_count": 0}

    def _table_columns(self, table):
        self.env.cr.execute("SELECT column_name FROM information_schema.columns WHERE table_name = %s", [table])
        return {row[0] for row in self.env.cr.fetchall()}

    def _get_target_summary(self, filters):
        domain = [
            ("active", "=", True),
            ("company_id", "in", filters["company_ids"]),
            ("date_start", "<=", filters["date_end"]),
            ("date_end", ">=", filters["date_start"]),
        ]
        if filters.get("pos_config_ids"):
            domain += ["|", ("pos_config_id", "=", False), ("pos_config_id", "in", filters["pos_config_ids"])]
        if filters.get("cashier_ids"):
            domain += ["|", ("cashier_id", "=", False), ("cashier_id", "in", filters["cashier_ids"])]
        if filters.get("waiter_ids"):
            domain += ["|", ("waiter_id", "=", False), ("waiter_id", "in", filters["waiter_ids"])]
        targets = self.env["pos.analytics.target"].search(domain)
        kpis = self._get_basic_sales_for_targets(filters)
        target_amount = sum(targets.mapped("target_amount"))
        target_orders = sum(targets.mapped("target_orders"))
        target_aov = sum(targets.mapped("target_avg_order_value")) / len(targets) if targets else 0.0
        remaining = max(target_amount - kpis["actual_sales"], 0.0)
        days_remaining = max((fields.Date.to_date(filters["date_end"]) - fields.Date.context_today(self.with_context(tz=filters["timezone"]))).days + 1, 1)
        return {
            "target_count": len(targets),
            "monthly_target": target_amount,
            "actual_sales": kpis["actual_sales"],
            "achievement_percentage": (kpis["actual_sales"] / target_amount * 100.0) if target_amount else 0.0,
            "remaining_target": remaining,
            "required_average_daily_sales": remaining / days_remaining if remaining else 0.0,
            "target_orders": target_orders,
            "actual_orders": kpis["actual_orders"],
            "orders_target_achievement": (kpis["actual_orders"] / target_orders * 100.0) if target_orders else 0.0,
            "target_avg_order_value": target_aov,
            "actual_avg_order_value": kpis["actual_avg_order_value"],
            "avg_order_value_target_achievement": (kpis["actual_avg_order_value"] / target_aov * 100.0) if target_aov else 0.0,
        }

    def _get_basic_sales_for_targets(self, filters):
        where, params = self._order_where(filters, alias="po")
        row = self._fetchone_dict(f"""
            SELECT COALESCE(SUM(po.amount_total), 0) AS actual_sales, COUNT(po.id) AS actual_orders
            FROM pos_order po WHERE {where}
        """, params)
        row["actual_avg_order_value"] = row["actual_sales"] / row["actual_orders"] if row["actual_orders"] else 0.0
        return row


    def _get_daily_closing(self, filters):
        where, params = self._order_where(filters, alias="po")
        metric_expr = self._order_basis_expr(filters, "po")
        session_columns = self._table_columns("pos_session")
        opening_expr = "ps.cash_register_balance_start" if "cash_register_balance_start" in session_columns else "0.0"
        closing_expr = "ps.cash_register_balance_end_real" if "cash_register_balance_end_real" in session_columns else ("ps.cash_register_balance_end" if "cash_register_balance_end" in session_columns else "0.0")
        rows = self._fetchall_dict(f"""
            SELECT (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %s)::date AS business_date,
                   pc.name AS branch_name, ps.name AS session_name, ps.start_at AS opening_time, ps.stop_at AS closing_time,
                   COALESCE({opening_expr}, 0.0) AS opening_balance, COALESCE({closing_expr}, 0.0) AS closing_balance,
                   COALESCE(rp.name, ru.login, 'No Cashier') AS cashier_name,
                   COALESCE(SUM(CASE WHEN po.amount_total >= 0 THEN {metric_expr} ELSE 0 END), 0) AS total_sales,
                   COALESCE(SUM(po.amount_total), 0) AS net_sales,
                   COUNT(po.id) AS total_orders,
                   COALESCE(SUM(CASE WHEN po.amount_total < 0 THEN ABS(po.amount_total) ELSE 0 END), 0) AS refunds,
                   COALESCE(SUM(po.amount_tax), 0) AS tax
            FROM pos_order po
            LEFT JOIN pos_config pc ON pc.id = po.config_id
            LEFT JOIN pos_session ps ON ps.id = po.session_id
            LEFT JOIN res_users ru ON ru.id = po.user_id
            LEFT JOIN res_partner rp ON rp.id = ru.partner_id
            WHERE {where}
            GROUP BY business_date, pc.name, ps.name, ps.start_at, ps.stop_at, opening_balance, closing_balance, cashier_name
            ORDER BY business_date, branch_name, session_name, cashier_name
        """, [filters["timezone"]] + params)
        payments = self._daily_closing_payments(filters)
        discounts = self._daily_closing_discounts(filters)
        waiters = self._daily_closing_waiters(filters)
        for row in rows:
            key = (str(row["business_date"]), row["branch_name"], row["session_name"], row["cashier_name"])
            payment = payments.get(key, {})
            row["cash_sales"] = payment.get("cash", 0.0)
            row["bank_card_sales"] = payment.get("bank", 0.0)
            row["mobile_money_sales"] = payment.get("mobile", 0.0)
            row["other_payment_methods"] = payment.get("other", 0.0)
            row["total_collected"] = row["cash_sales"] + row["bank_card_sales"] + row["mobile_money_sales"] + row["other_payment_methods"]
            row["payment_method_breakdown"] = payment.get("breakdown", [])
            row["discounts"] = discounts.get(key, 0.0)
            row["waiter_breakdown"] = waiters.get(key, [])
            row["average_order_value"] = row["total_sales"] / row["total_orders"] if row["total_orders"] else 0.0
        return rows

    def _daily_closing_payments(self, filters):
        where, params = self._order_where(filters, alias="po")
        rows = self._fetchall_dict(f"""
            SELECT (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %s)::date AS business_date, pc.name AS branch_name,
                   ps.name AS session_name, COALESCE(rp.name, ru.login, 'No Cashier') AS cashier_name,
                   ppm.name AS payment_method_name, COALESCE(ppm.journal_id, 0) AS journal_id, COALESCE(SUM(pp.amount), 0) AS amount
            FROM pos_payment pp
            JOIN pos_order po ON po.id = pp.pos_order_id
            LEFT JOIN pos_config pc ON pc.id = po.config_id
            LEFT JOIN pos_session ps ON ps.id = po.session_id
            LEFT JOIN res_users ru ON ru.id = po.user_id
            LEFT JOIN res_partner rp ON rp.id = ru.partner_id
            JOIN pos_payment_method ppm ON ppm.id = pp.payment_method_id
            WHERE {where}
            GROUP BY business_date, pc.name, ps.name, cashier_name, ppm.name, ppm.journal_id
        """, [filters["timezone"]] + params)
        journal_ids = [r["journal_id"] for r in rows if r.get("journal_id")]
        journal_types = {j.id: j.type for j in self.env["account.journal"].browse(journal_ids)}
        grouped = defaultdict(lambda: {"cash": 0.0, "bank": 0.0, "mobile": 0.0, "other": 0.0, "breakdown": []})
        for row in rows:
            key = (str(row["business_date"]), row["branch_name"], row["session_name"], row["cashier_name"])
            method_type = self._classify_payment(row["payment_method_name"], journal_types.get(row.get("journal_id")))
            grouped[key][method_type] += row["amount"]
            grouped[key]["breakdown"].append({"payment_method_name": row["payment_method_name"], "amount": row["amount"]})
        return grouped

    def _daily_closing_discounts(self, filters):
        where, params = self._line_where(filters)
        rows = self._fetchall_dict(f"""
            SELECT (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %s)::date AS business_date, pc.name AS branch_name,
                   ps.name AS session_name, COALESCE(rp.name, ru.login, 'No Cashier') AS cashier_name,
                   COALESCE(SUM(ABS(pol.qty) * pol.price_unit * pol.discount / 100.0), 0) AS discounts
            FROM pos_order_line pol
            JOIN pos_order po ON po.id = pol.order_id
            JOIN product_product pp ON pp.id = pol.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            LEFT JOIN pos_config pc ON pc.id = po.config_id
            LEFT JOIN pos_session ps ON ps.id = po.session_id
            LEFT JOIN res_users ru ON ru.id = po.user_id
            LEFT JOIN res_partner rp ON rp.id = ru.partner_id
            WHERE {where}
            GROUP BY business_date, pc.name, ps.name, cashier_name
        """, [filters["timezone"]] + params)
        return {(str(r["business_date"]), r["branch_name"], r["session_name"], r["cashier_name"]): r["discounts"] for r in rows}

    def _daily_closing_waiters(self, filters):
        where, params = self._line_where(filters)
        basis_expr = self._line_basis_expr(filters, "pol")
        rows = self._fetchall_dict(f"""
            SELECT (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %s)::date AS business_date, pc.name AS branch_name,
                   ps.name AS session_name, COALESCE(rp.name, ru.login, 'No Cashier') AS cashier_name,
                   COALESCE(he.name, 'No Waiter') AS waiter_name, COALESCE(SUM({basis_expr}), 0) AS sales
            FROM pos_order_line pol
            JOIN pos_order po ON po.id = pol.order_id
            JOIN product_product pp ON pp.id = pol.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            LEFT JOIN pos_config pc ON pc.id = po.config_id
            LEFT JOIN pos_session ps ON ps.id = po.session_id
            LEFT JOIN res_users ru ON ru.id = po.user_id
            LEFT JOIN res_partner rp ON rp.id = ru.partner_id
            LEFT JOIN hr_employee he ON he.id = po.employee_id
            WHERE {where}
            GROUP BY business_date, pc.name, ps.name, cashier_name, waiter_name
        """, [filters["timezone"]] + params)
        grouped = defaultdict(list)
        for row in rows:
            grouped[(str(row["business_date"]), row["branch_name"], row["session_name"], row["cashier_name"])].append({"waiter_name": row["waiter_name"], "sales": row["sales"]})
        return grouped

    @api.model
    def get_report_data(self, filters=None):
        self._check_analytics_access()
        filters = self._normalize_filters(filters or {})
        settings = self._get_settings()
        data = self.get_dashboard_data(dict(filters, include_raw_orders=filters.get("include_raw_orders")))
        data["sections"] = self._report_sections(filters.get("report_type"))
        data["grouped_report"] = self.get_grouped_report_data(filters)
        data["payment_analytics"] = self._get_payment_analytics(filters)
        data["refund_discount_summary"] = self._get_refund_discount_summary(filters)
        data["tax_details"] = self._get_tax_details(filters)
        data["daily_closing_details"] = self._get_daily_closing_details(filters)
        if not settings["enable_target_cards"]:
            data["target_summary"] = {}
        return data

    def _report_sections(self, report_type):
        report_type = report_type or "management_summary"
        mapping = {
            "sales_summary": ["kpis", "grouped", "sales_trend", "branch_comparison", "payment_methods", "refund_discount", "tax_summary"],
            "daily_closing": ["daily_closing", "daily_closing_payments", "daily_closing_cashiers", "daily_closing_waiters", "daily_closing_orders"],
            "product_sales": ["grouped", "top_products"],
            "category_sales": ["grouped", "top_categories"],
            "waiter_performance": ["grouped", "waiter_performance", "top_products"],
            "cashier_performance": ["grouped", "cashier_performance", "payment_methods"],
            "branch_comparison": ["grouped", "branch_comparison", "payment_methods"],
            "hourly_sales": ["grouped", "peak_hours", "peak_hour_day_heatmap"],
            "daily_sales": ["grouped", "sales_trend"],
            "refund_discount": ["refund_discount", "refund_breakdowns", "discount_breakdowns"],
            "payment_method": ["grouped", "payment_methods", "payment_breakdowns", "payment_category_summary"],
            "tax": ["tax_summary", "tax_details"],
            "management_summary": [
                "kpis", "grouped", "sales_trend", "top_products", "top_categories", "waiter_performance",
                "cashier_performance", "branch_comparison", "peak_hours", "peak_days", "peak_hour_day_heatmap",
                "payment_methods", "payment_breakdowns", "refund_discount", "tax_summary", "target_summary",
            ],
        }
        return mapping.get(report_type, mapping["management_summary"])

    def get_grouped_report_data(self, filters=None):
        self._check_analytics_access()
        filters = self._normalize_filters(filters or {})
        group_by = filters.get("group_by") or "day"
        if group_by == "payment_method":
            return self._get_grouped_payment_method_report(filters)
        where, params = self._line_where(filters)
        basis_expr = self._line_basis_expr(filters, "pol")
        group_defs = self._group_sql_definition(group_by, filters)
        payment_join = ""
        rows = self._fetchall_dict(f"""
            SELECT {group_defs['select']} AS group_label,
                   {group_defs.get('extra_select', '')}
                   COALESCE(SUM(CASE WHEN pol.qty >= 0 THEN {basis_expr} ELSE 0 END), 0) AS total_sales,
                   COALESCE(SUM(pol.price_subtotal_incl), 0) AS net_sales,
                   COUNT(DISTINCT po.id) AS order_count,
                   COALESCE(SUM(pol.qty), 0) AS quantity_sold,
                   COALESCE(SUM(po.amount_tax) / NULLIF(COUNT(pol.id), 0), 0) AS tax,
                   COALESCE(SUM(CASE WHEN pol.price_subtotal_incl < 0 THEN ABS(pol.price_subtotal_incl) ELSE 0 END), 0) AS refunds,
                   COALESCE(SUM(ABS(pol.qty) * pol.price_unit * pol.discount / 100.0), 0) AS discounts
            FROM pos_order_line pol
            JOIN pos_order po ON po.id = pol.order_id
            JOIN product_product pp ON pp.id = pol.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            LEFT JOIN product_category pc ON pc.id = pt.categ_id
            LEFT JOIN pos_config pconf ON pconf.id = po.config_id
            LEFT JOIN pos_session ps ON ps.id = po.session_id
            LEFT JOIN res_users ru ON ru.id = po.user_id
            LEFT JOIN res_partner rp ON rp.id = ru.partner_id
            LEFT JOIN hr_employee he ON he.id = po.employee_id
            {payment_join}
            WHERE {where}
            GROUP BY {group_defs['group_by']}
            ORDER BY total_sales DESC, group_label
            LIMIT 500
        """, group_defs.get("params", []) + params)
        for row in rows:
            row["average_order_value"] = row["total_sales"] / row["order_count"] if row["order_count"] else 0.0
        return rows

    def _get_grouped_payment_method_report(self, filters):
        rows = self._payment_group_rows(filters)
        total = sum(row.get("amount", 0.0) for row in rows) or 0.0
        for row in rows:
            row.update({
                "group_label": row.get("payment_method_name"),
                "payment_method_id": row.get("payment_method_id"),
                "total_sales": row.get("amount", 0.0),
                "net_sales": row.get("amount", 0.0),
                "order_count": row.get("order_count", 0),
                "quantity_sold": 0.0,
                "quantity_not_applicable": True,
                "average_order_value": row.get("amount", 0.0) / row.get("order_count", 1) if row.get("order_count") else 0.0,
                "tax": 0.0,
                "refunds": abs(row.get("amount", 0.0)) if row.get("amount", 0.0) < 0 else 0.0,
                "discounts": 0.0,
                "percentage": row.get("amount", 0.0) / total * 100.0 if total else 0.0,
            })
        return rows

    def _group_sql_definition(self, group_by, filters):
        tz = filters.get("timezone") or DEFAULT_TZ
        lang = self.env.lang or "en_US"
        local_dt = f"(po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %s)"
        defs = {
            "day": {"select": f"TO_CHAR({local_dt}::date, 'YYYY-MM-DD')", "group_by": "1", "params": [tz]},
            "week": {"select": f"TO_CHAR(date_trunc('week', {local_dt}), 'IYYY-IW')", "group_by": "1", "params": [tz]},
            "month": {"select": f"TO_CHAR(date_trunc('month', {local_dt}), 'YYYY-MM')", "group_by": "1", "params": [tz]},
            "year": {"select": f"TO_CHAR(date_trunc('year', {local_dt}), 'YYYY')", "group_by": "1", "params": [tz]},
            "product": {"select": "COALESCE(pt.name->>%s, pt.name->>'en_US', pp.default_code, 'Product')", "group_by": "1", "params": [lang], "extra_select": "pol.product_id AS product_id,"},
            "category": {"select": "COALESCE(pc.complete_name, pc.name, 'No Category')", "group_by": "1", "params": [], "extra_select": "pt.categ_id AS category_id,"},
            "cashier": {"select": "COALESCE(rp.name, ru.login, 'No Cashier')", "group_by": "1", "params": [], "extra_select": "po.user_id AS cashier_id,"},
            "waiter": {"select": "COALESCE(he.name, 'No Waiter')", "group_by": "1", "params": [], "extra_select": "po.employee_id AS waiter_id,"},
            "branch": {"select": "COALESCE(pconf.name, 'No Branch')", "group_by": "1", "params": [], "extra_select": "po.config_id AS branch_id,"},
            "payment_method": {"select": "COALESCE(ppm.name, 'No Payment Method')", "group_by": "1", "params": [], "extra_select": "ppm.id AS payment_method_id,"},
            "hour": {"select": f"TO_CHAR({local_dt}, 'HH24:00')", "group_by": "1", "params": [tz]},
            "weekday": {"select": f"TO_CHAR({local_dt}, 'Day')", "group_by": "1, EXTRACT(ISODOW FROM " + local_dt + ")", "params": [tz, tz]},
            "session": {"select": "COALESCE(ps.name, 'No Session')", "group_by": "1", "params": [], "extra_select": "po.session_id AS session_id,"},
        }
        res = defs.get(group_by, defs["day"])
        res.setdefault("extra_select", "")
        return res

    def _get_peak_hour_day_heatmap(self, filters):
        where, params = self._order_where(filters, alias="po")
        metric_expr = self._order_basis_expr(filters, "po")
        rows = self._fetchall_dict(f"""
            SELECT EXTRACT(ISODOW FROM (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %s))::int AS day_number,
                   EXTRACT(HOUR FROM (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %s))::int AS hour,
                   COUNT(po.id) AS order_count,
                   COALESCE(SUM({metric_expr}), 0) AS sales_amount
            FROM pos_order po
            WHERE {where}
            GROUP BY 1, 2
            ORDER BY 1, 2
        """, [filters["timezone"], filters["timezone"]] + params)
        for row in rows:
            row["day_label"] = calendar.day_abbr[row["day_number"] - 1]
            row["label"] = "%s %02d:00" % (row["day_label"], row["hour"])
        return rows

    def _get_payment_analytics(self, filters):
        rows = self._payment_group_rows(filters)
        total = sum(row.get("amount", 0.0) for row in rows) or 0.0
        for row in rows:
            row["percentage"] = row.get("amount", 0.0) / total * 100.0 if total else 0.0
        return {
            "summary": rows,
            "category_summary": self._payment_category_summary(rows),
            "branch_breakdown": self._payment_breakdown(filters, "branch"),
            "cashier_breakdown": self._payment_breakdown(filters, "cashier"),
            "date_breakdown": self._payment_breakdown(filters, "date"),
        }


    def _payment_category_summary(self, rows):
        grouped = defaultdict(lambda: {"method_type": "", "amount": 0.0, "order_count": 0})
        for row in rows:
            key = row.get("method_type") or "other"
            grouped[key]["method_type"] = key
            grouped[key]["amount"] += row.get("amount", 0.0)
            grouped[key]["order_count"] += row.get("order_count", 0)
        total = sum(row["amount"] for row in grouped.values()) or 0.0
        result = []
        for row in grouped.values():
            row["percentage"] = row["amount"] / total * 100.0 if total else 0.0
            result.append(row)
        return sorted(result, key=lambda r: r["amount"], reverse=True)

    def _payment_breakdown(self, filters, group):
        where, params = self._order_where(filters, alias="po")
        if group == "branch":
            select = "COALESCE(pc.name, 'No Branch') AS group_label"
            joins = "LEFT JOIN pos_config pc ON pc.id = po.config_id"
            groupby = "group_label"
            extra_params = []
        elif group == "cashier":
            select = "COALESCE(rp.name, ru.login, 'No Cashier') AS group_label"
            joins = "LEFT JOIN res_users ru ON ru.id = po.user_id LEFT JOIN res_partner rp ON rp.id = ru.partner_id"
            groupby = "group_label"
            extra_params = []
        else:
            select = "TO_CHAR((po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %s)::date, 'YYYY-MM-DD') AS group_label"
            joins = ""
            groupby = "group_label"
            extra_params = [filters["timezone"]]
        rows = self._fetchall_dict(f"""
            SELECT {select}, ppm.name AS payment_method_name, COALESCE(SUM(pp.amount), 0) AS amount, COUNT(DISTINCT po.id) AS order_count
            FROM pos_payment pp
            JOIN pos_order po ON po.id = pp.pos_order_id
            JOIN pos_payment_method ppm ON ppm.id = pp.payment_method_id
            {joins}
            WHERE {where}
            GROUP BY {groupby}, ppm.name
            ORDER BY group_label, amount DESC
        """, extra_params + params)
        return rows

    def _get_tax_details(self, filters):
        return {
            "by_date": self._tax_breakdown(filters, "date"),
            "by_branch": self._tax_breakdown(filters, "branch"),
            "by_category": self._tax_breakdown(filters, "category"),
            "by_session": self._tax_breakdown(filters, "session"),
        }

    def _tax_breakdown(self, filters, group):
        if group in ("category",):
            where, params = self._line_where(filters)
            return self._fetchall_dict(f"""
                SELECT COALESCE(pc.complete_name, pc.name, 'No Category') AS group_label,
                       COALESCE(SUM(po.amount_tax) / NULLIF(COUNT(pol.id), 0), 0) AS tax_amount,
                       COUNT(DISTINCT po.id) AS order_count
                FROM pos_order_line pol
                JOIN pos_order po ON po.id = pol.order_id
                JOIN product_product pp ON pp.id = pol.product_id
                JOIN product_template pt ON pt.id = pp.product_tmpl_id
                LEFT JOIN product_category pc ON pc.id = pt.categ_id
                WHERE {where}
                GROUP BY group_label
                ORDER BY tax_amount DESC
            """, params)
        where, params = self._order_where(filters, alias="po")
        if group == "branch":
            select, joins, extra = "COALESCE(pc.name, 'No Branch')", "LEFT JOIN pos_config pc ON pc.id = po.config_id", []
        elif group == "session":
            select, joins, extra = "COALESCE(ps.name, 'No Session')", "LEFT JOIN pos_session ps ON ps.id = po.session_id", []
        else:
            select, joins, extra = "TO_CHAR((po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %s)::date, 'YYYY-MM-DD')", "", [filters["timezone"]]
        return self._fetchall_dict(f"""
            SELECT {select} AS group_label, COALESCE(SUM(po.amount_tax), 0) AS tax_amount, COUNT(po.id) AS order_count
            FROM pos_order po
            {joins}
            WHERE {where}
            GROUP BY group_label
            ORDER BY group_label
        """, extra + params)

    def _get_daily_closing_details(self, filters):
        return {
            "summary": self._get_daily_closing(filters),
            "payments": self._daily_closing_payment_rows(filters),
            "cashiers": self._daily_closing_cashier_rows(filters),
            "waiters": self._daily_closing_waiter_rows(filters),
            "orders": self._get_raw_orders(dict(filters, include_raw_orders=True)),
        }

    def _daily_closing_payment_rows(self, filters):
        where, params = self._order_where(filters, alias="po")
        rows = self._fetchall_dict(f"""
            SELECT COALESCE(pc.name, 'No Branch') AS branch_name, COALESCE(ps.name, 'No Session') AS session_name,
                   ppm.name AS payment_method_name, COALESCE(SUM(pp.amount), 0) AS amount, COUNT(DISTINCT po.id) AS order_count
            FROM pos_payment pp
            JOIN pos_order po ON po.id = pp.pos_order_id
            JOIN pos_payment_method ppm ON ppm.id = pp.payment_method_id
            LEFT JOIN pos_config pc ON pc.id = po.config_id
            LEFT JOIN pos_session ps ON ps.id = po.session_id
            WHERE {where}
            GROUP BY pc.name, ps.name, ppm.name
            ORDER BY branch_name, session_name, amount DESC
        """, params)
        return rows

    def _daily_closing_cashier_rows(self, filters):
        rows = self._get_cashier_performance(filters, limit=500)
        for row in rows:
            row["orders"] = row.get("number_of_orders", 0)
            row["total_sales"] = row.get("total_collected", 0.0)
            row["collected_amount"] = row.get("total_collected", 0.0)
        return rows

    def _daily_closing_waiter_rows(self, filters):
        rows = self._get_waiter_performance(filters, limit=500)
        for row in rows:
            row["orders"] = row.get("total_orders", 0)
        return rows

    def _get_raw_orders(self, filters):
        where, params = self._order_where(filters, alias="po")
        rows = self._fetchall_dict(f"""
            SELECT po.id, po.name AS order_reference, po.date_order, pc.name AS branch_name, ps.name AS session_name,
                   COALESCE(rp.name, ru.login, '') AS cashier_name, COALESCE(he.name, '') AS waiter_name,
                   COALESCE(partner.name, '') AS customer_name, po.state AS order_state, po.amount_total AS total_amount,
                   po.amount_tax AS tax, po.amount_paid AS paid_amount, po.amount_return AS return_amount
            FROM pos_order po
            LEFT JOIN pos_config pc ON pc.id = po.config_id
            LEFT JOIN pos_session ps ON ps.id = po.session_id
            LEFT JOIN res_users ru ON ru.id = po.user_id
            LEFT JOIN res_partner rp ON rp.id = ru.partner_id
            LEFT JOIN hr_employee he ON he.id = po.employee_id
            LEFT JOIN res_partner partner ON partner.id = po.partner_id
            WHERE {where}
            ORDER BY po.date_order DESC, po.id DESC
            LIMIT 5000
        """, params)
        payment_map = self._raw_order_payments([r["id"] for r in rows])
        for row in rows:
            row["payment_methods"] = payment_map.get(row["id"], "")
        return rows

    def _raw_order_payments(self, order_ids):
        if not order_ids:
            return {}
        rows = self._fetchall_dict("""
            SELECT pp.pos_order_id AS order_id, STRING_AGG(ppm.name, ', ' ORDER BY ppm.name) AS payment_methods
            FROM pos_payment pp
            JOIN pos_payment_method ppm ON ppm.id = pp.payment_method_id
            WHERE pp.pos_order_id = ANY(%s)
            GROUP BY pp.pos_order_id
        """, [order_ids])
        return {r["order_id"]: r["payment_methods"] for r in rows}
