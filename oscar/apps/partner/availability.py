from django.utils.translation import gettext_lazy as _


class Base(object):
    """
    Base availability policy.
    基本可用性政策。
    """

    #: Availability code.  This is used for HTML classes
    # 可用性代码。 这用于HTML类
    code = ''

    #: A description of the availability of a product.  This is shown on the
    #: product detail page.  Eg "In stock", "Out of stock" etc
    # 产品可用性的描述。 这将显示在产品详细信息页面上。 例如“有货”，“缺货”等
    message = ''

    #: When this item should be dispatched
    # 何时应该发送此项目
    dispatch_date = None

    @property
    def short_message(self):
        """
        A shorter version of the availability message, suitable for showing on
        browsing pages.
        可用性消息的较短版本，适合在浏览页面上显示。
        """
        return self.message

    @property
    def is_available_to_buy(self):
        """
        Test if this product is available to be bought.  This is used for
        validation when a product is added to a user's basket.
        测试是否可以购买此产品。 这用于在将产品添加到用户购物篮时进行验证。
        """
        # We test a purchase of a single item
        # 我们测试购买单个商品
        return self.is_purchase_permitted(1)[0]

    def is_purchase_permitted(self, quantity):
        """
        Test whether a proposed purchase is allowed

        Should return a boolean and a reason
        测试是否允许建议购买应返回布尔值和原因
        """
        return False, _("unavailable")


# Common availability policies
# 常见的可用性策略


class Unavailable(Base):
    """
    Policy for when a product is unavailable
    产品何时不可用的政策
    """
    code = 'unavailable'
    message = _("Unavailable")


class Available(Base):
    """
    For when a product is always available, irrespective of stock level.

    This might be appropriate for digital products where stock doesn't need to
    be tracked and the product is always available to buy.

    当产品始终可用时，无论库存level如何。
    这可能适用于不需要跟踪库存且始终可以购买产品的数字产品。
    """
    code = 'available'
    message = _("Available")

    def is_purchase_permitted(self, quantity):
        return True, ""


class StockRequired(Base):
    """
    Allow a product to be bought while there is stock.  This policy is
    instantiated with a stock number (``num_available``).  It ensures that the
    product is only available to buy while there is stock available.

    This is suitable for physical products where back orders (eg allowing
    purchases when there isn't stock available) are not permitted.

    允许在有库存的情况下购买产品。 此策略使用库存号（``num_available``）进行实例化。
    它确保产品仅在有库存时才可以购买。
    这适用于不允许退货订单（例如，在没有库存时允许购买）的实物产品。
    """
    CODE_IN_STOCK = 'instock'
    CODE_OUT_OF_STOCK = 'outofstock'

    def __init__(self, num_available):
        self.num_available = num_available

    def is_purchase_permitted(self, quantity):
        if self.num_available <= 0:
            return False, _("no stock available")
        if quantity > self.num_available:
            msg = _("a maximum of %(max)d can be bought") % {
                'max': self.num_available}
            return False, msg
        return True, ""

    @property
    def code(self):
        if self.num_available > 0:
            return self.CODE_IN_STOCK
        return self.CODE_OUT_OF_STOCK

    @property
    def short_message(self):
        if self.num_available > 0:
            return _("In stock")
        return _("Unavailable")

    @property
    def message(self):
        if self.num_available > 0:
            return _("In stock (%d available)") % self.num_available
        return _("Unavailable")
