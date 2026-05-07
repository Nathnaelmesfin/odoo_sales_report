/** @odoo-module **/

import { registry } from "@web/core/registry";

export const posAnalyticsService = {
    dependencies: ["orm"],
    start(env, { orm }) {
        return {
            async getFilterOptions() {
                return orm.call("pos.analytics.service", "get_filter_options", []);
            },
            async getDashboardData(filters) {
                return orm.call("pos.analytics.service", "get_dashboard_data", [filters]);
            },
        };
    },
};

registry.category("services").add("pos_analytics", posAnalyticsService);
