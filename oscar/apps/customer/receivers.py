from django.dispatch import receiver

from oscar.apps.catalogue.signals import product_viewed

from . import history


@receiver(product_viewed)
def receive_product_view(sender, product, user, request, response, **kwargs):
    """
    Receiver to handle viewing single product pages

    Requires the request and response objects due to dependence on cookies

    接收器处理查看单个产品页面

    由于依赖cookie，需要请求和响应对象
    """
    return history.update(product, request, response)
