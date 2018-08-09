from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


# 用户仪表板配置
class UsersDashboardConfig(AppConfig):
    label = 'users_dashboard'
    name = 'oscar.apps.dashboard.users'
    verbose_name = _('Users dashboard')
