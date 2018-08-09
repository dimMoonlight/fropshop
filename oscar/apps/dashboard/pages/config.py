from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


# 页面仪表板配置
class PagesDashboardConfig(AppConfig):
    label = 'pages_dashboard'
    name = 'oscar.apps.dashboard.pages'
    verbose_name = _('Pages dashboard')
