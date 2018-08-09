from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


# 通信仪表板配置
class CommunicationsDashboardConfig(AppConfig):
    label = 'communications_dashboard'
    name = 'oscar.apps.dashboard.communications'
    verbose_name = _('Communications dashboard')
