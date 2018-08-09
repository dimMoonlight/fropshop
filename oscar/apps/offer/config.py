from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


# 报价配置
class OfferConfig(AppConfig):
    label = 'offer'
    name = 'oscar.apps.offer'
    verbose_name = _('Offer')

    def ready(self):
        from . import signals  # noqa