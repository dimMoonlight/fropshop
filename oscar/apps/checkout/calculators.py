from oscar.core import prices


# 订单总计算器
class OrderTotalCalculator(object):
    """
    Calculator class for calculating the order total.
    计算器类用于计算订单总数。
    """

    def __init__(self, request=None):
        # We store a reference to the request as the total may
        # depend on the user or the other checkout data in the session.
        # Further, it is very likely that it will as shipping method
        # always changes the order total.
        # 我们存储对请求的引用，因为总数可能取决于用户或会话中的其他结账数据。
        # 此外，很可能它将作为运输方法始终更改订单总数。
        self.request = request

    # 计算
    def calculate(self, basket, shipping_charge, **kwargs):
        excl_tax = basket.total_excl_tax + shipping_charge.excl_tax
        if basket.is_tax_known and shipping_charge.is_tax_known:
            incl_tax = basket.total_incl_tax + shipping_charge.incl_tax
        else:
            incl_tax = None
        return prices.Price(
            currency=basket.currency,
            excl_tax=excl_tax, incl_tax=incl_tax)
