from decimal import Decimal as D

from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import gettext_lazy as _

from oscar.core.loading import get_classes

(Free, NoShippingRequired,
 TaxExclusiveOfferDiscount, TaxInclusiveOfferDiscount) \
    = get_classes('shipping.methods', ['Free', 'NoShippingRequired',
                                       'TaxExclusiveOfferDiscount', 'TaxInclusiveOfferDiscount'])


class Repository(object):
    """
    Repository class responsible for returning ShippingMethod
    objects for a given user, basket etc
    存储库类负责为给定用户，购物篮等返回ShippingMethod对象
    """

    # We default to just free shipping. Customise this class and override this
    # property to add your own shipping methods. This should be a list of
    # instantiated shipping methods.
    # 我们默认只是免费送货。 自定义此类并覆盖此属性以添加您自己的送货方式。
    # 这应该是实例化的运输方法列表。
    methods = (Free(),)

    # API

    def get_shipping_methods(self, basket, shipping_addr=None, **kwargs):
        """
        Return a list of all applicable shipping method instances for a given
        basket, address etc.
        返回给定购物篮，地址等所有适用的送货方法实例的列表。
        """
        if not basket.is_shipping_required():
            # Special case! Baskets that don't require shipping get a special
            # shipping method.
            # 特例！ 不需要运输的购物篮可以获得特殊的运输方式。
            return [NoShippingRequired()]

        methods = self.get_available_shipping_methods(
            basket=basket, shipping_addr=shipping_addr, **kwargs)
        if basket.has_shipping_discounts:
            methods = self.apply_shipping_offers(basket, methods)
        return methods

    def get_default_shipping_method(self, basket, shipping_addr=None,
                                    **kwargs):
        """
        Return a 'default' shipping method to show on the basket page to give
        the customer an indication of what their order will cost.
        返回“默认”送货方式以显示在购物篮页面上，以便向客户说明其订单的成本。
        """
        shipping_methods = self.get_shipping_methods(
            basket, shipping_addr=shipping_addr, **kwargs)
        if len(shipping_methods) == 0:
            raise ImproperlyConfigured(
                _("You need to define some shipping methods"))

        # Assume first returned method is default
        # 假设第一个返回的方法是默认的
        return shipping_methods[0]

    # Helpers

    def get_available_shipping_methods(
            self, basket, shipping_addr=None, **kwargs):
        """
        Return a list of all applicable shipping method instances for a given
        basket, address etc. This method is intended to be overridden.
        返回给定购物篮，地址等所有适用的送货方法实例的列表。此方法旨在被覆盖。
        """
        return self.methods

    def apply_shipping_offers(self, basket, methods):
        """
        Apply shipping offers to the passed set of methods
        将运送优惠应用于传递的方法集
        """
        # We default to only applying the first shipping discount.
        # 我们默认只应用第一个运费折扣。
        offer = basket.shipping_discounts[0]['offer']
        return [self.apply_shipping_offer(basket, method, offer)
                for method in methods]

    def apply_shipping_offer(self, basket, method, offer):
        """
        Wrap a shipping method with an offer discount wrapper (as long as the
        shipping charge is non-zero).
        使用优惠折扣包装包装运费方式（只要运费不为零）。
        """
        # If the basket has qualified for shipping discount, wrap the shipping
        # method with a decorating class that applies the offer discount to the
        # shipping charge.
        # 如果购物篮有资格享受运费折扣，请将运费方法包装在装修类中，并将优惠折
        # 扣应用于运费。
        charge = method.calculate(basket)
        if charge.excl_tax == D('0.00'):
            # No need to wrap zero shipping charges
            # 无需包含零运费
            return method

        if charge.is_tax_known:
            return TaxInclusiveOfferDiscount(method, offer)
        else:
            # When returning a tax exclusive discount, it is assumed
            # that this will be used to calculate taxes which will then
            # be assigned directly to the method instance.
            # 当返回税收专用折扣时，假设这将用于计算税收，然后将直接分配给方法实例。
            return TaxExclusiveOfferDiscount(method, offer)
