from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


# 订单仪表板配置
class OrdersDashboardConfig(AppConfig):
    label = 'orders_dashboard'
    name = 'oscar.apps.dashboard.orders'
    verbose_name = _('Orders dashboard')
