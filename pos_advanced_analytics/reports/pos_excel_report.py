# -*- coding: utf-8 -*-

from io import BytesIO

import xlsxwriter

from odoo import api, fields, models, _


class ReportPosAnalyticsPdf(models.AbstractModel):
    _name = "report.pos_advanced_analytics.pos_sales_report_template"
    _description = "POS Analytics PDF Report"

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env["pos.analytics.report.wizard"].browse(docids)
        wizard = docs[:1]
        payload = wizard._report_payload() if wizard else {}
        return {"doc_ids": docids, "doc_model": "pos.analytics.report.wizard", "docs": docs, "data": payload}


class PosAnalyticsExcelReport(models.AbstractModel):
    _name = "pos.analytics.excel.report"
    _description = "POS Analytics Excel Report Builder"

    def generate_xlsx(self, wizard, filters=None):
        wizard._check_analytics_access()
        filters = filters or wizard._filters()
        data = self.env["pos.analytics.service"].get_report_data(filters)
        output = BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        formats = self._formats(workbook)
        meta = self._metadata(wizard, filters, data)
        self._summary_sheet(workbook, formats, meta, data)
        for sheet in self._sheets_for_report(wizard.report_type, wizard.include_raw_orders):
            self._write_named_sheet(workbook, formats, meta, data, sheet)
        workbook.close()
        output.seek(0)
        return output.read()

    def _metadata(self, wizard, filters, data):
        return {
            "title": dict(wizard._fields["report_type"].selection).get(wizard.report_type, wizard.report_type),
            "date_range": "%s to %s" % (filters["date_start"], filters["date_end"]),
            "branch": ", ".join(wizard.pos_config_ids.mapped("name")) or _("All POS Branches"),
            "cashier": ", ".join(wizard.cashier_ids.mapped("name")) or _("All Cashiers"),
            "waiter": ", ".join(wizard.waiter_ids.mapped("name")) or _("All Waiters"),
            "category": ", ".join(wizard.product_category_ids.mapped("complete_name")) or _("All Categories"),
            "payment": ", ".join(wizard.payment_method_ids.mapped("name")) or _("All Payment Methods"),
            "basis": data.get("basis_label", ""),
            "group_by": dict(wizard._fields["group_by"].selection).get(wizard.group_by, wizard.group_by),
            "timezone": filters.get("timezone"),
            "generated_by": self.env.user.name,
            "generated_at": fields.Datetime.context_timestamp(wizard, fields.Datetime.now()).strftime("%Y-%m-%d %H:%M:%S"),
        }

    def _sheets_for_report(self, report_type, include_raw_orders=False):
        sheets = {
            "sales_summary": ["Grouped Summary", "Sales Trend", "Branch Comparison", "Payment Methods", "Refunds & Discounts", "Tax Summary"],
            "daily_closing": ["Daily Closing Summary", "Payment Breakdown", "Cashier Breakdown", "Waiter Breakdown", "Order Summary"],
            "product_sales": ["Grouped Summary", "Product Sales"],
            "category_sales": ["Grouped Summary", "Category Sales"],
            "waiter_performance": ["Grouped Summary", "Waiter Sales", "Product Sales"],
            "cashier_performance": ["Grouped Summary", "Cashier Sales", "Payment Methods"],
            "branch_comparison": ["Grouped Summary", "Branch Comparison", "Payment Breakdown"],
            "hourly_sales": ["Grouped Summary", "Peak Hours", "Peak Hour Heatmap"],
            "daily_sales": ["Grouped Summary", "Sales Trend"],
            "refund_discount": ["Refunds & Discounts", "Refund By Product", "Refund By Category", "Refund By Cashier", "Discount By Product", "Discount By Category", "Discount By Cashier"],
            "payment_method": ["Grouped Summary", "Payment Methods", "Payment Breakdown"],
            "tax": ["Tax Summary", "Tax By Date", "Tax By Branch", "Tax By Category", "Tax By Session"],
            "management_summary": ["Grouped Summary", "Sales Trend", "Product Sales", "Category Sales", "Waiter Sales", "Cashier Sales", "Peak Hours", "Peak Days", "Peak Hour Heatmap", "Payment Methods", "Refunds & Discounts", "Tax Summary", "Branch Comparison"],
        }.get(report_type, [])
        if include_raw_orders and "Order Summary" not in sheets:
            sheets.append("Raw POS Orders")
        return sheets

    def _write_named_sheet(self, workbook, formats, meta, data, name):
        refund = data.get("refund_discount_summary", {})
        tax = data.get("tax_details", {})
        daily = data.get("daily_closing_details", {})
        payment = data.get("payment_analytics", {})
        mapping = {
            "Grouped Summary": (data.get("grouped_report", []), self._cols_grouped()),
            "Sales Trend": (data.get("sales_trend", []), [("label", "Period"), ("total_sales", "Sales"), ("net_sales", "Net Sales"), ("order_count", "Orders"), ("tax_amount", "Tax")]),
            "Product Sales": (data.get("top_products", []), [("product_name", "Product"), ("category_name", "Category"), ("quantity_sold", "Quantity Sold"), ("gross_sales", "Gross Sales"), ("net_sales", "Net Sales"), ("discount_amount", "Discount Amount"), ("refund_quantity", "Refund Quantity"), ("refund_amount", "Refund Amount"), ("average_unit_price", "Average Unit Price")]),
            "Category Sales": (data.get("top_categories", []), [("category_name", "Category"), ("quantity_sold", "Quantity Sold"), ("gross_sales", "Gross Sales"), ("net_sales", "Net Sales"), ("discount_amount", "Discount Amount"), ("refund_quantity", "Refund Quantity"), ("refund_amount", "Refund Amount"), ("product_count", "Products Sold")]),
            "Waiter Sales": (data.get("waiter_performance", []), [("waiter_name", "Waiter"), ("total_sales", "Total Sales"), ("total_orders", "Orders"), ("average_order_value", "AOV"), ("quantity_sold", "Quantity"), ("refunds", "Refunds"), ("discounts", "Discounts")]),
            "Cashier Sales": (data.get("cashier_performance", []), [("cashier_name", "Cashier"), ("total_collected", "Collected"), ("number_of_orders", "Orders"), ("average_ticket_size", "Average Ticket"), ("refunds", "Refunds"), ("discounts", "Discounts"), ("payment_method_breakdown", "Payment Breakdown")]),
            "Peak Hours": (data.get("peak_hours", []), [("label", "Hour"), ("order_count", "Orders"), ("sales_amount", "Sales")]),
            "Peak Days": (data.get("peak_days", []), [("label", "Day"), ("order_count", "Orders"), ("sales_amount", "Sales")]),
            "Peak Hour Heatmap": (data.get("peak_hour_day_heatmap", []), [("day_label", "Day"), ("hour", "Hour"), ("order_count", "Orders"), ("sales_amount", "Sales")]),
            "Payment Methods": (payment.get("summary", data.get("payment_methods", [])), [("payment_method_name", "Payment Method"), ("method_type", "Category"), ("order_count", "Orders"), ("amount", "Amount"), ("percentage", "Share %")]),
            "Payment Breakdown": (payment.get("branch_breakdown", []), [("group_label", "Group"), ("payment_method_name", "Payment Method"), ("order_count", "Orders"), ("amount", "Amount")]),
            "Refunds & Discounts": ([refund], [("total_refund_amount", "Refund Total"), ("refund_order_count", "Refund Orders"), ("refund_quantity", "Refund Quantity"), ("discount_amount", "Discount Total"), ("discounted_order_count", "Discounted Orders")]),
            "Refund By Product": (refund.get("refund_by_product", []), [("name", "Product"), ("refund_amount", "Refund Amount"), ("refund_quantity", "Refund Quantity"), ("order_count", "Orders")]),
            "Refund By Category": (refund.get("refund_by_category", []), [("name", "Category"), ("refund_amount", "Refund Amount"), ("refund_quantity", "Refund Quantity"), ("order_count", "Orders")]),
            "Refund By Cashier": (refund.get("refund_by_cashier", []), [("name", "Cashier"), ("refund_amount", "Refund Amount"), ("refund_quantity", "Refund Quantity"), ("order_count", "Orders")]),
            "Discount By Product": (refund.get("discount_by_product", []), [("name", "Product"), ("discount_amount", "Discount Amount")]),
            "Discount By Category": (refund.get("discount_by_category", []), [("name", "Category"), ("discount_amount", "Discount Amount")]),
            "Discount By Cashier": (refund.get("discount_by_cashier", []), [("name", "Cashier"), ("discount_amount", "Discount Amount")]),
            "Tax Summary": (data.get("tax_summary", []), [("branch_name", "Branch"), ("order_count", "Orders"), ("tax_amount", "Tax")]),
            "Tax By Date": (tax.get("by_date", []), [("group_label", "Date"), ("order_count", "Orders"), ("tax_amount", "Tax")]),
            "Tax By Branch": (tax.get("by_branch", []), [("group_label", "Branch"), ("order_count", "Orders"), ("tax_amount", "Tax")]),
            "Tax By Category": (tax.get("by_category", []), [("group_label", "Category"), ("order_count", "Orders"), ("tax_amount", "Tax")]),
            "Tax By Session": (tax.get("by_session", []), [("group_label", "Session"), ("order_count", "Orders"), ("tax_amount", "Tax")]),
            "Branch Comparison": (data.get("branch_comparison", []), [("branch_name", "Branch"), ("total_sales", "Sales"), ("net_sales", "Net Sales"), ("total_orders", "Orders"), ("average_order_value", "AOV"), ("top_product", "Top Product"), ("top_category", "Top Category"), ("peak_hour", "Peak Hour"), ("peak_day", "Peak Day")]),
            "Daily Closing Summary": (daily.get("summary", data.get("daily_closing", [])), [("business_date", "Date"), ("branch_name", "Branch"), ("session_name", "Session"), ("cashier_name", "Cashier"), ("opening_time", "Opening"), ("closing_time", "Closing"), ("opening_balance", "Opening Balance"), ("closing_balance", "Closing Balance"), ("total_sales", "Sales"), ("total_collected", "Collected"), ("net_sales", "Net Sales"), ("total_orders", "Orders"), ("cash_sales", "Cash"), ("bank_card_sales", "Bank/Card"), ("mobile_money_sales", "Mobile"), ("other_payment_methods", "Other"), ("refunds", "Refunds"), ("discounts", "Discounts"), ("tax", "Tax"), ("average_order_value", "AOV")]),
            "Cashier Breakdown": (daily.get("cashiers", []), [("cashier_name", "Cashier"), ("orders", "Orders"), ("total_sales", "Sales"), ("collected_amount", "Collected"), ("refunds", "Refunds"), ("discounts", "Discounts")]),
            "Waiter Breakdown": (daily.get("waiters", []), [("waiter_name", "Waiter"), ("orders", "Orders"), ("total_sales", "Sales"), ("quantity_sold", "Quantity"), ("refunds", "Refunds"), ("discounts", "Discounts")]),
            "Order Summary": (daily.get("orders", []), self._cols_raw_orders()),
            "Raw POS Orders": (data.get("raw_orders", []), self._cols_raw_orders()),
        }
        rows, cols = mapping.get(name, ([], []))
        self._table_sheet(workbook, formats, meta, name, rows, cols)

    def _cols_grouped(self):
        return [("group_label", "Group"), ("total_sales", "Sales"), ("net_sales", "Net Sales"), ("order_count", "Orders"), ("quantity_sold", "Quantity"), ("average_order_value", "AOV"), ("tax", "Tax"), ("refunds", "Refunds"), ("discounts", "Discounts")]

    def _cols_raw_orders(self):
        return [("order_reference", "Order"), ("date_order", "Date/time"), ("branch_name", "Branch"), ("session_name", "Session"), ("cashier_name", "Cashier"), ("waiter_name", "Waiter"), ("customer_name", "Customer"), ("order_state", "State"), ("total_amount", "Total"), ("tax", "Tax"), ("paid_amount", "Paid"), ("return_amount", "Return"), ("payment_methods", "Payment Methods")]

    def _formats(self, workbook):
        return {
            "title": workbook.add_format({"bold": True, "font_size": 16, "font_color": "#111827"}),
            "meta_label": workbook.add_format({"bold": True, "font_color": "#4b5563"}),
            "meta": workbook.add_format({"font_color": "#4b5563"}),
            "header": workbook.add_format({"bold": True, "bg_color": "#1f4e79", "font_color": "white", "border": 1}),
            "money": workbook.add_format({"num_format": "#,##0.00", "border": 1}),
            "number": workbook.add_format({"num_format": "#,##0.00", "border": 1}),
            "integer": workbook.add_format({"num_format": "#,##0", "border": 1}),
            "date": workbook.add_format({"num_format": "yyyy-mm-dd hh:mm", "border": 1}),
            "text": workbook.add_format({"border": 1}),
            "total": workbook.add_format({"bold": True, "bg_color": "#e5e7eb", "border": 1, "num_format": "#,##0.00"}),
        }

    def _write_meta(self, sheet, formats, meta, width):
        sheet.merge_range(0, 0, 0, max(width - 1, 1), meta["title"], formats["title"])
        rows = [("Date range", "date_range"), ("POS branch/shop", "branch"), ("Cashier", "cashier"), ("Waiter", "waiter"), ("Product category", "category"), ("Payment method", "payment"), ("Report basis", "basis"), ("Group by", "group_by"), ("Generated by", "generated_by"), ("Generated datetime", "generated_at"), ("Timezone", "timezone")]
        for index, (label, key) in enumerate(rows, start=1):
            sheet.write(index, 0, _(label), formats["meta_label"])
            sheet.write(index, 1, meta.get(key, ""), formats["meta"])

    def _summary_sheet(self, workbook, formats, meta, data):
        sheet = workbook.add_worksheet("Summary")
        self._write_meta(sheet, formats, meta, 5)
        row = 14
        sheet.write_row(row, 0, [_('KPI'), _('Value')], formats["header"])
        for key, value in (data.get("kpis") or {}).items():
            if isinstance(value, (dict, list)):
                continue
            row += 1
            sheet.write(row, 0, key.replace("_", " ").title(), formats["text"])
            self._write_value(sheet, row, 1, value, formats)
        sheet.set_column(0, 0, 36)
        sheet.set_column(1, 1, 28)
        sheet.freeze_panes(15, 0)

    def _table_sheet(self, workbook, formats, meta, name, rows, columns):
        sheet = workbook.add_worksheet(name[:31])
        self._write_meta(sheet, formats, meta, max(len(columns), 2))
        header_row = 14
        sheet.write_row(header_row, 0, [label for key, label in columns], formats["header"])
        totals = [0.0] * len(columns)
        for r_index, row in enumerate(rows or [], header_row + 1):
            for c_index, (key, label) in enumerate(columns):
                value = self._display_value(row.get(key, ""))
                self._write_value(sheet, r_index, c_index, value, formats)
                if isinstance(value, (int, float)):
                    totals[c_index] += value
        total_row = header_row + 1 + len(rows or [])
        sheet.write(total_row, 0, _("Totals"), formats["total"])
        for c_index in range(1, len(columns)):
            sheet.write(total_row, c_index, totals[c_index] if totals[c_index] else "", formats["total"])
        if columns:
            sheet.autofilter(header_row, 0, total_row, len(columns) - 1)
        for c_index, (key, label) in enumerate(columns):
            values = [len(str(label))] + [len(str(self._display_value(r.get(key, "")))) for r in (rows or [])[:100]]
            sheet.set_column(c_index, c_index, min(max(max(values) + 2, 12), 48))
        if rows and len(columns) > 1:
            numeric_cols = [i for i, (key, label) in enumerate(columns) if any(isinstance(r.get(key), (int, float)) for r in rows)]
            for col in numeric_cols[:2]:
                sheet.conditional_format(header_row + 1, col, total_row - 1, col, {"type": "3_color_scale"})
        sheet.freeze_panes(header_row + 1, 0)

    def _write_value(self, sheet, row, col, value, formats):
        if isinstance(value, int):
            sheet.write(row, col, value, formats["integer"])
        elif isinstance(value, float):
            sheet.write(row, col, value, formats["number"])
        else:
            sheet.write(row, col, value if value is not None else "", formats["text"])

    def _display_value(self, value):
        if isinstance(value, list):
            return "; ".join("%s: %s" % (item.get("payment_method_name") or item.get("waiter_name") or item.get("name", ""), item.get("amount", item.get("sales", item.get("discount_amount", item.get("refund_amount", ""))))) for item in value)
        if isinstance(value, dict):
            return ", ".join("%s: %s" % (k, v) for k, v in value.items())
        return value if value is not None else ""
