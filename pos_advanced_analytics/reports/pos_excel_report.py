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
        return {
            "doc_ids": docids,
            "doc_model": "pos.analytics.report.wizard",
            "docs": docs,
            "data": payload,
        }


class PosAnalyticsExcelReport(models.AbstractModel):
    _name = "pos.analytics.excel.report"
    _description = "POS Analytics Excel Report Builder"

    def generate_xlsx(self, wizard, filters=None):
        filters = filters or wizard._filters()
        data = self.env["pos.analytics.service"].get_dashboard_data(filters)
        output = BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        formats = self._formats(workbook)
        meta = {
            "title": dict(wizard._fields["report_type"].selection).get(wizard.report_type, wizard.report_type),
            "date_range": "%s to %s" % (filters["date_start"], filters["date_end"]),
            "branch": ", ".join(wizard.pos_config_ids.mapped("name")) or _("All POS Branches"),
            "generated_by": self.env.user.name,
            "generated_at": fields.Datetime.context_timestamp(wizard, fields.Datetime.now()).strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._summary_sheet(workbook, formats, meta, data)
        self._table_sheet(workbook, formats, meta, "Daily Sales", data.get("sales_trend", []), [
            ("label", "Period"), ("total_sales", "Total Sales"), ("net_sales", "Net Sales"), ("order_count", "Orders"), ("tax_amount", "Tax"),
        ])
        self._table_sheet(workbook, formats, meta, "Daily Closing", data.get("daily_closing", []), [
            ("business_date", "Date"), ("branch_name", "POS Branch"), ("session_name", "POS Session"),
            ("cashier_name", "Cashier"), ("opening_time", "Opening Time"), ("closing_time", "Closing Time"),
            ("total_sales", "Total Sales"), ("net_sales", "Net Sales"), ("total_orders", "Total Orders"),
            ("cash_sales", "Cash Sales"), ("bank_card_sales", "Bank/Card Sales"), ("mobile_money_sales", "Mobile Money Sales"),
            ("other_payment_methods", "Other Payment Methods"), ("refunds", "Refunds"), ("discounts", "Discounts"),
            ("tax", "Tax"), ("average_order_value", "Average Order Value"), ("payment_method_breakdown", "Payment Method Breakdown"),
            ("waiter_breakdown", "Waiter Breakdown"),
        ])
        self._table_sheet(workbook, formats, meta, "Product Sales", data.get("top_products", []), [
            ("product_name", "Product"), ("category_name", "Category"), ("quantity_sold", "Quantity Sold"),
            ("gross_sales", "Gross Sales"), ("discount_amount", "Discount Amount"), ("net_sales", "Net Sales"),
            ("refund_quantity", "Refund Quantity"), ("refund_amount", "Refund Amount"),
        ])
        self._table_sheet(workbook, formats, meta, "Category Sales", data.get("top_categories", []), [
            ("category_name", "Category"), ("quantity_sold", "Quantity Sold"), ("gross_sales", "Gross Sales"),
            ("discount_amount", "Discount Amount"), ("net_sales", "Net Sales"), ("refund_quantity", "Refund Quantity"),
            ("refund_amount", "Refund Amount"),
        ])
        self._table_sheet(workbook, formats, meta, "Waiter Sales", data.get("waiter_performance", []), [
            ("waiter_name", "Waiter"), ("total_sales", "Total Sales"), ("total_orders", "Total Orders"),
            ("average_order_value", "Average Order Value"), ("quantity_sold", "Quantity Sold"), ("refunds", "Refunds"),
            ("discounts", "Discounts"),
        ])
        self._table_sheet(workbook, formats, meta, "Cashier Sales", data.get("cashier_performance", []), [
            ("cashier_name", "Cashier"), ("total_collected", "Total Collected"), ("number_of_orders", "Orders"),
            ("average_ticket_size", "Average Ticket Size"), ("refunds", "Refunds"), ("discounts", "Discounts"),
            ("payment_method_breakdown", "Payment Method Breakdown"),
        ])
        self._table_sheet(workbook, formats, meta, "Peak Hours", data.get("peak_hours", []), [
            ("label", "Hour"), ("order_count", "Orders"), ("sales_amount", "Sales Amount"),
        ])
        self._table_sheet(workbook, formats, meta, "Peak Days", data.get("peak_days", []), [
            ("label", "Day"), ("order_count", "Orders"), ("sales_amount", "Sales Amount"),
        ])
        self._table_sheet(workbook, formats, meta, "Payment Methods", data.get("payment_methods", []), [
            ("payment_method_name", "Payment Method"), ("method_type", "Type"), ("order_count", "Orders"), ("amount", "Amount"),
        ])
        refund = data.get("refund_discount_summary", {})
        self._table_sheet(workbook, formats, meta, "Refunds & Discounts", [refund], [
            ("total_refund_amount", "Total Refund Amount"), ("refund_order_count", "Refund Order Count"),
            ("discount_amount", "Discount Amount"), ("discounted_order_count", "Discounted Order Count"),
        ])
        self._table_sheet(workbook, formats, meta, "Tax Summary", data.get("tax_summary", []), [
            ("branch_name", "Branch"), ("order_count", "Orders"), ("tax_amount", "Tax Amount"),
        ])
        self._table_sheet(workbook, formats, meta, "Branch Comparison", data.get("branch_comparison", []), [
            ("branch_name", "Branch"), ("total_sales", "Total Sales"), ("net_sales", "Net Sales"),
            ("total_orders", "Orders"), ("average_order_value", "Average Order Value"), ("top_product", "Top Product"),
            ("top_category", "Top Category"), ("peak_hour", "Peak Hour"), ("peak_day", "Peak Day"),
        ])
        if wizard.include_raw_orders:
            self._table_sheet(workbook, formats, meta, "Raw POS Orders", data.get("raw_orders", []), [
                ("order_reference", "Order Reference"), ("date_order", "Date/time"), ("branch_name", "POS Branch"),
                ("session_name", "Session"), ("cashier_name", "Cashier"), ("waiter_name", "Waiter"),
                ("customer_name", "Customer"), ("order_state", "Order State"), ("total_amount", "Total Amount"),
                ("tax", "Tax"), ("paid_amount", "Paid Amount"), ("return_amount", "Return Amount"),
                ("payment_methods", "Payment Methods"),
            ])
        workbook.close()
        output.seek(0)
        return output.read()

    def _formats(self, workbook):
        return {
            "title": workbook.add_format({"bold": True, "font_size": 16, "font_color": "#111827"}),
            "meta": workbook.add_format({"font_color": "#4b5563"}),
            "header": workbook.add_format({"bold": True, "bg_color": "#1f4e79", "font_color": "white", "border": 1}),
            "money": workbook.add_format({"num_format": "#,##0.00", "border": 1}),
            "number": workbook.add_format({"num_format": "#,##0.00", "border": 1}),
            "integer": workbook.add_format({"num_format": "#,##0", "border": 1}),
            "text": workbook.add_format({"border": 1}),
            "total": workbook.add_format({"bold": True, "bg_color": "#e5e7eb", "border": 1, "num_format": "#,##0.00"}),
        }

    def _write_meta(self, sheet, formats, meta, width):
        sheet.merge_range(0, 0, 0, max(width - 1, 1), meta["title"], formats["title"])
        sheet.write(1, 0, _("Date range"), formats["meta"])
        sheet.write(1, 1, meta["date_range"], formats["meta"])
        sheet.write(2, 0, _("POS branch filter"), formats["meta"])
        sheet.write(2, 1, meta["branch"], formats["meta"])
        sheet.write(3, 0, _("Generated by"), formats["meta"])
        sheet.write(3, 1, meta["generated_by"], formats["meta"])
        sheet.write(4, 0, _("Generated datetime"), formats["meta"])
        sheet.write(4, 1, meta["generated_at"], formats["meta"])

    def _summary_sheet(self, workbook, formats, meta, data):
        sheet = workbook.add_worksheet("Summary")
        self._write_meta(sheet, formats, meta, 4)
        sheet.write_row(6, 0, [_("KPI"), _("Value")], formats["header"])
        row = 7
        for key, value in (data.get("kpis") or {}).items():
            sheet.write(row, 0, key.replace("_", " ").title(), formats["text"])
            sheet.write(row, 1, self._display_value(value), formats["number"] if isinstance(value, (int, float)) else formats["text"])
            row += 1
        sheet.set_column(0, 0, 36)
        sheet.set_column(1, 1, 24)
        sheet.freeze_panes(7, 0)

    def _table_sheet(self, workbook, formats, meta, name, rows, columns):
        sheet = workbook.add_worksheet(name[:31])
        self._write_meta(sheet, formats, meta, len(columns))
        header_row = 6
        sheet.write_row(header_row, 0, [label for key, label in columns], formats["header"])
        totals = [0.0] * len(columns)
        for r_index, row in enumerate(rows, header_row + 1):
            for c_index, (key, label) in enumerate(columns):
                value = self._display_value(row.get(key, ""))
                fmt = formats["number"] if isinstance(value, (int, float)) else formats["text"]
                sheet.write(r_index, c_index, value, fmt)
                if isinstance(value, (int, float)):
                    totals[c_index] += value
        total_row = header_row + 1 + len(rows)
        sheet.write(total_row, 0, _("Totals"), formats["total"])
        for c_index in range(1, len(columns)):
            if totals[c_index]:
                sheet.write(total_row, c_index, totals[c_index], formats["total"])
            else:
                sheet.write(total_row, c_index, "", formats["total"])
        for c_index, (key, label) in enumerate(columns):
            max_len = max([len(str(label))] + [len(str(self._display_value(r.get(key, "")))) for r in rows[:100]])
            sheet.set_column(c_index, c_index, min(max(max_len + 2, 12), 45))
        sheet.freeze_panes(header_row + 1, 0)

    def _display_value(self, value):
        if isinstance(value, list):
            return "; ".join("%s: %s" % (item.get("payment_method_name") or item.get("waiter_name") or item.get("name", ""), item.get("amount", item.get("sales", item.get("discount_amount", "")))) for item in value)
        if isinstance(value, dict):
            return ", ".join("%s: %s" % (k, v) for k, v in value.items())
        return value if value is not None else ""
