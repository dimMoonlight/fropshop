from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


# 运输仪表板配置
class ShippingDashboardConfig(AppConfig):
    label = 'shipping_dashboard'
    name = 'oscar.apps.dashboard.shipping'
    verbose_name = _('Shipping dashboard')
