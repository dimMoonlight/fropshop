from decimal import Decimal as D


class OfferApplications(object):
    """
    A collection of offer applications and the discounts that they give.

    Each offer application is stored as a dict which has fields for:

    * The offer that led to the successful application
    * The result instance
    * The number of times the offer was successfully applied

    一系列优惠申请及其提供的折扣。
    每个商品应用程序都存储为dict，其中包含以下字段：
    * 导致成功申请的优惠
    * 结果实例
    * 成功应用要约的次数
    """
    def __init__(self):
        self.applications = {}

    def __iter__(self):
        return self.applications.values().__iter__()

    def __len__(self):
        return len(self.applications)

    def add(self, offer, result):
        if offer.id not in self.applications:
            self.applications[offer.id] = {
                'offer': offer,
                'result': result,
                'name': offer.name,
                'description': result.description,
                'voucher': offer.get_voucher(),
                'freq': 0,
                'discount': D('0.00')}
        self.applications[offer.id]['discount'] += result.discount
        self.applications[offer.id]['freq'] += 1

    @property
    def offer_discounts(self):
        """
        Return basket discounts from offers (but not voucher offers)
        返回折扣优惠（但不提供凭单）
        """
        discounts = []
        for application in self.applications.values():
            if not application['voucher'] and application['discount'] > 0:
                discounts.append(application)
        return discounts

    @property
    def voucher_discounts(self):
        """
        Return basket discounts from vouchers.
        返回优惠券折扣
        """
        discounts = []
        for application in self.applications.values():
            if application['voucher'] and application['discount'] > 0:
                discounts.append(application)
        return discounts

    @property
    def shipping_discounts(self):
        """
        Return shipping discounts
        返回运输折扣
        """
        discounts = []
        for application in self.applications.values():
            if application['result'].affects_shipping:
                discounts.append(application)
        return discounts

    @property
    def grouped_voucher_discounts(self):
        """
        Return voucher discounts aggregated up to the voucher level.

        This is different to the voucher_discounts property as a voucher can
        have multiple offers associated with it.

        返回优惠券折扣汇总至优惠券级别。

        这与voucher_discounts（优惠券折扣)属性不同，因为优惠券可以有多个与之关联的优惠。
        """
        voucher_discounts = {}
        for application in self.voucher_discounts:
            voucher = application['voucher']
            discount = application['discount']
            if voucher.code not in voucher_discounts:
                voucher_discounts[voucher.code] = {
                    'voucher': voucher,
                    'discount': discount,
                }
            else:
                voucher_discounts[voucher.code]['discount'] += discount
        return voucher_discounts.values()

    @property
    def post_order_actions(self):
        """
        Return successful offer applications which didn't lead to a discount
        返回不会导致折扣的成功报价申请
        """
        applications = []
        for application in self.applications.values():
            if application['result'].affects_post_order:
                applications.append(application)
        return applications

    @property
    def offers(self):
        """
        Return a dict of offers that were successfully applied
        返回已成功应用的商品的字典
        """
        return dict([(a['offer'].id, a['offer']) for a in
                     self.applications.values()])


class ApplicationResult(object):
    is_final = is_successful = False
    # Basket discount 购物篮折扣
    discount = D('0.00')
    description = None

    # Offer applications can affect 3 distinct things
    # (a) Give a discount off the BASKET total
    # (b) Give a discount off the SHIPPING total
    # (a) Trigger a post-order action

    # 优惠应用程序可以影响3个不同的事
    # (a) 给予购物篮总额折扣
    # (b) 给予运输总额折扣
    # (a) 触发下订单后的行动
    BASKET, SHIPPING, POST_ORDER = 0, 1, 2
    affects = None

    @property
    def affects_basket(self):
        return self.affects == self.BASKET

    @property
    def affects_shipping(self):
        return self.affects == self.SHIPPING

    @property
    def affects_post_order(self):
        return self.affects == self.POST_ORDER


class BasketDiscount(ApplicationResult):
    """
    For when an offer application leads to a simple discount off the basket's
    total
    当一个报价申请导致一购物篮总额的简单折扣
    """
    affects = ApplicationResult.BASKET

    def __init__(self, amount):
        self.discount = amount

    @property
    def is_successful(self):
        return self.discount > 0

    def __str__(self):
        return '<Basket discount of %s>' % self.discount

    def __repr__(self):
        return '%s(%r)' % (self.__class__.__name__, self.discount)


# Helper global as returning zero discount is quite common
# 帮助全球作为返回零折扣是很常见的
ZERO_DISCOUNT = BasketDiscount(D('0.00'))


class ShippingDiscount(ApplicationResult):
    """
    For when an offer application leads to a discount from the shipping cost
    当优惠申请导致运费成本折扣时
    """
    is_successful = is_final = True
    affects = ApplicationResult.SHIPPING


SHIPPING_DISCOUNT = ShippingDiscount()


class PostOrderAction(ApplicationResult):
    """
    For when an offer condition is met but the benefit is deferred until after
    the order has been placed.  Eg buy 2 books and get 100 loyalty points.
    对于满足要约条件但是在订单下达之前延期的利益。 例如，买2本书，获得100忠诚度积分。
    """
    is_final = is_successful = True
    affects = ApplicationResult.POST_ORDER

    def __init__(self, description):
        self.description = description
