from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


# 购物篮配置
class BasketConfig(AppConfig):
    label = 'basket'
    name = 'oscar.apps.basket'
    verbose_name = _('Basket')
