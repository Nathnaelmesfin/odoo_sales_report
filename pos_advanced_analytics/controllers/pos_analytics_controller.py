# -*- coding: utf-8 -*-

import json
from urllib.parse import unquote

from odoo import http, _
from odoo.http import request
from werkzeug.exceptions import Forbidden, NotFound


class PosAnalyticsController(http.Controller):

    @http.route("/pos_advanced_analytics/report/xlsx/<int:wizard_id>", type="http", auth="user")
    def download_xlsx(self, wizard_id, filters=None, **kwargs):
        if not request.env.user.has_group("pos_advanced_analytics.group_pos_analytics_user"):
            raise Forbidden()
        wizard = request.env["pos.analytics.report.wizard"].browse(wizard_id).exists()
        if not wizard:
            raise NotFound()
        parsed_filters = json.loads(unquote(filters)) if filters else wizard._filters()
        content = request.env["pos.analytics.excel.report"].generate_xlsx(wizard, parsed_filters)
        filename = "%s_%s.xlsx" % (wizard.report_type, wizard.date_end)
        return request.make_response(content, headers=[
            ("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            ("Content-Disposition", http.content_disposition(filename)),
        ])
