from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


# 评论仪表板配置
class ReviewsDashboardConfig(AppConfig):
    label = 'reviews_dashboard'
    name = 'oscar.apps.dashboard.reviews'
    verbose_name = _('Reviews dashboard')
