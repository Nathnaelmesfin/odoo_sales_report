/** @odoo-module **/

import { Component, onMounted, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const KPI_DEFINITIONS = [
    ["total_sales", "Total Sales", "currency"], ["net_sales", "Net Sales", "currency"],
    ["total_orders", "Total Orders", "number"], ["average_order_value", "Average Order Value", "currency"],
    ["total_quantity_sold", "Total Quantity Sold", "number"], ["total_discounts", "Total Discounts", "currency"],
    ["total_refunds", "Total Refunds", "currency"], ["total_tax", "Total Tax", "currency"],
    ["cash_sales", "Cash Sales", "currency"], ["bank_card_sales", "Bank/Card Sales", "currency"],
    ["mobile_money_sales", "Mobile Money Sales", "currency"], ["best_selling_product", "Best Selling Product", "text"],
    ["best_selling_category", "Best Selling Category", "text"], ["top_waiter", "Top Waiter", "text"],
    ["top_cashier", "Top Cashier", "text"], ["peak_sales_hour", "Peak Sales Hour", "text"],
    ["peak_sales_day", "Peak Sales Day", "text"], ["dine_in_sales", "Dine-in Sales", "currency"],
    ["takeaway_sales", "Takeaway Sales", "currency"], ["branch_sales_comparison_summary", "Branch Sales Comparison", "text"],
    ["sales_per_hour", "Sales Per Hour", "currency"], ["sales_per_waiter", "Sales Per Waiter", "currency"],
    ["sales_per_cashier", "Sales Per Cashier", "currency"],
];

export class PosAnalyticsDashboard extends Component {
    static template = "pos_advanced_analytics.Dashboard";

    setup() {
        this.analytics = useService("pos_analytics");
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({
            loading: true,
            error: null,
            options: {},
            data: {},
            filters: {
                date_range: "today",
                date_start: null,
                date_end: null,
                pos_config_ids: [],
                cashier_ids: [],
                waiter_ids: [],
                product_category_ids: [],
                product_ids: [],
                payment_method_ids: [],
                report_basis: "incl",
                group_by: "day",
            },
        });
        this.timer = null;
        onMounted(async () => {
            await this.bootstrap();
            this.startAutoRefresh();
        });
        onWillUnmount(() => this.stopAutoRefresh());
    }

    get kpiCards() {
        const kpis = this.state.data.kpis || {};
        const settings = this.state.data.settings || this.state.options.defaults || {};
        return KPI_DEFINITIONS.filter(([key]) => {
            if (["top_waiter", "sales_per_waiter"].includes(key) && !settings.enable_waiter_analytics) return false;
            if (["top_cashier", "sales_per_cashier"].includes(key) && !settings.enable_cashier_analytics) return false;
            if (["dine_in_sales", "takeaway_sales"].includes(key) && !kpis.dine_takeaway_available) return false;
            return true;
        }).map(([key, label, type]) => ({ key, label, type, value: this.formatValue(kpis[key], type) }));
    }

    get hasData() {
        return !!(this.state.data.kpis && Object.keys(this.state.data.kpis).length);
    }

    async bootstrap() {
        try {
            this.state.loading = true;
            this.state.error = null;
            const options = await this.analytics.getFilterOptions();
            this.state.options = options;
            const defaults = options.defaults || {};
            this.state.filters.date_range = defaults.date_range || "today";
            this.state.filters.report_basis = "incl";
            if (defaults.default_pos_config_id) {
                this.state.filters.pos_config_ids = [defaults.default_pos_config_id];
            }
            await this.loadData();
        } catch (error) {
            this.handleError(error);
        } finally {
            this.state.loading = false;
        }
    }

    async loadData() {
        this.state.loading = true;
        try {
            this.state.data = await this.analytics.getDashboardData(this.state.filters);
            this.state.filters.date_start = this.state.data.filters.date_start;
            this.state.filters.date_end = this.state.data.filters.date_end;
            this.state.error = null;
        } catch (error) {
            this.handleError(error);
        } finally {
            this.state.loading = false;
        }
    }

    handleError(error) {
        this.state.error = error.message || String(error);
        this.notification.add(this.state.error, { title: "POS Analytics", type: "danger" });
    }

    startAutoRefresh() {
        this.stopAutoRefresh();
        const seconds = Number(this.state.options.defaults?.auto_refresh_interval || 60);
        this.timer = setInterval(() => this.loadData(), Math.max(seconds, 30) * 1000);
    }

    stopAutoRefresh() {
        if (this.timer) {
            clearInterval(this.timer);
            this.timer = null;
        }
    }

    async onFilterChange(ev) {
        const name = ev.target.name;
        if (ev.target.multiple) {
            this.state.filters[name] = [...ev.target.selectedOptions].map((option) => Number(option.value)).filter(Boolean);
        } else {
            this.state.filters[name] = ev.target.value;
        }
        if (name === "date_range" && ev.target.value !== "custom") {
            this.state.filters.date_start = null;
            this.state.filters.date_end = null;
        }
        await this.loadData();
    }

    async openReportWizard() {
        await this.action.doAction("pos_advanced_analytics.action_pos_analytics_report_wizard", {
            additionalContext: {
                default_date_start: this.state.filters.date_start,
                default_date_end: this.state.filters.date_end,
                default_report_basis: this.state.filters.report_basis,
            },
        });
    }

    async exportPdf() {
        const wizardId = await this.createWizard("pdf");
        await this.action.doAction({
            type: "ir.actions.report",
            report_type: "qweb-pdf",
            report_name: "pos_advanced_analytics.pos_sales_report_template",
            res_id: wizardId,
            context: { active_ids: [wizardId] },
        });
    }

    async exportExcel() {
        const wizardId = await this.createWizard("xlsx");
        await this.action.doAction({
            type: "ir.actions.act_url",
            url: `/pos_advanced_analytics/report/xlsx/${wizardId}`,
            target: "self",
        });
    }

    async createWizard(format) {
        const ids = await this.orm.create("pos.analytics.report.wizard", [{
            date_start: this.state.filters.date_start,
            date_end: this.state.filters.date_end,
            pos_config_ids: [[6, 0, this.state.filters.pos_config_ids || []]],
            cashier_ids: [[6, 0, this.state.filters.cashier_ids || []]],
            waiter_ids: [[6, 0, this.state.filters.waiter_ids || []]],
            product_category_ids: [[6, 0, this.state.filters.product_category_ids || []]],
            product_ids: [[6, 0, this.state.filters.product_ids || []]],
            payment_method_ids: [[6, 0, this.state.filters.payment_method_ids || []]],
            report_basis: this.state.filters.report_basis,
            group_by: this.state.filters.group_by,
            report_type: "management_summary",
            export_format: format,
            include_summary: true,
        }]);
        return Array.isArray(ids) ? ids[0] : ids;
    }

    formatValue(value, type = "text") {
        if (value === undefined || value === null || value === "") {
            return type === "text" ? "—" : "0";
        }
        if (type === "currency") {
            return Number(value || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        }
        if (type === "number") {
            return Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });
        }
        return String(value);
    }

    barWidth(value, rows, key) {
        const max = Math.max(...(rows || []).map((row) => Number(row[key] || 0)), 0);
        return max ? `${Math.max((Number(value || 0) / max) * 100, 3)}%` : "0%";
    }

    chartRows(rows, labelKey, valueKey, limit = 12) {
        const values = (rows || []).slice(0, limit).map((row) => ({ label: row[labelKey] || row.label || "—", value: Number(row[valueKey] || 0) }));
        const max = Math.max(...values.map((row) => row.value), 0);
        return values.map((row, index) => ({ ...row, index, width: max ? Math.max(row.value / max * 100, 2) : 0 }));
    }

    linePoints(rows, valueKey = "total_sales") {
        const values = (rows || []).map((row) => Number(row[valueKey] || 0));
        if (!values.length) return "";
        const max = Math.max(...values, 1);
        const step = values.length > 1 ? 300 / (values.length - 1) : 300;
        return values.map((value, index) => `${index * step},${90 - (value / max) * 80}`).join(" ");
    }

    donutSegments(rows, valueKey = "amount") {
        const values = (rows || []).map((row) => Number(row[valueKey] || 0));
        const total = values.reduce((sum, value) => sum + value, 0);
        let offset = 25;
        return (rows || []).slice(0, 6).map((row, index) => {
            const value = Number(row[valueKey] || 0);
            const length = total ? value / total * 100 : 0;
            const segment = { row, index, length, offset, color: ["#2563eb", "#14b8a6", "#f59e0b", "#ef4444", "#8b5cf6", "#64748b"][index % 6] };
            offset -= length;
            return segment;
        });
    }

    heatmapRows(rows) {
        const values = rows || [];
        const max = Math.max(...values.map((row) => Number(row.sales_amount || 0)), 0);
        return values.map((row) => ({ ...row, opacity: max ? 0.15 + (Number(row.sales_amount || 0) / max) * 0.85 : 0.15 }));
    }
}

registry.category("actions").add("pos_advanced_analytics.dashboard", PosAnalyticsDashboard);
