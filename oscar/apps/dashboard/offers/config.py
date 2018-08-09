from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


# 报价仪表板配置
class OffersDashboardConfig(AppConfig):
    label = 'offers_dashboard'
    name = 'oscar.apps.dashboard.offers'
    verbose_name = _('Offers dashboard')
