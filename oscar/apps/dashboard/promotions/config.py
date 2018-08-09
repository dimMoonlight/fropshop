from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


# 促销仪表板配置
class PromotionsDashboardConfig(AppConfig):
    label = 'promotions_dashboard'
    name = 'oscar.apps.dashboard.promotions'
    verbose_name = _('Promotions dashboard')
