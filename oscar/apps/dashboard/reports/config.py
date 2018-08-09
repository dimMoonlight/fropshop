from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


# 报告应用程序配置
class ReportsDashboardConfig(AppConfig):
    label = 'reports_dashboard'
    name = 'oscar.apps.dashboard.reports'
    verbose_name = _('Reports dashboard')
