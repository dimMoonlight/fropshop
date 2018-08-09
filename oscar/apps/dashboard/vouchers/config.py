from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


# 优惠券仪表板配置
class VouchersDashboardConfig(AppConfig):
    label = 'vouchers_dashboard'
    name = 'oscar.apps.dashboard.vouchers'
    verbose_name = _('Vouchers dashboard')
