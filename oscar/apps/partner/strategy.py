from collections import namedtuple
from decimal import Decimal as D

from oscar.core.loading import get_class

Unavailable = get_class('partner.availability', 'Unavailable')
Available = get_class('partner.availability', 'Available')
StockRequiredAvailability = get_class('partner.availability', 'StockRequired')
UnavailablePrice = get_class('partner.prices', 'Unavailable')
FixedPrice = get_class('partner.prices', 'FixedPrice')
TaxInclusiveFixedPrice = get_class('partner.prices', 'TaxInclusiveFixedPrice')

# A container for policies
# 政策的容器
PurchaseInfo = namedtuple(
    'PurchaseInfo', ['price', 'availability', 'stockrecord'])


class Selector(object):
    """
    Responsible for returning the appropriate strategy class for a given
    user/session.

    This can be called in three ways:

    #) Passing a request and user.  This is for determining
       prices/availability for a normal user browsing the site.

    #) Passing just the user.  This is for offline processes that don't
       have a request instance but do know which user to determine prices for.

    #) Passing nothing.  This is for offline processes that don't
       correspond to a specific user.  Eg, determining a price to store in
       a search index.

    负责为给定的用户/会话返回适当的策略类。
    这可以通过三种方式调用：
    ＃）传递请求和用户。 这用于确定浏览站点的普通用户的价格/可用性。
    ＃）仅传递用户。 这适用于没有请求实例但确实知道要确定价格的用户的脱机进程。
    ＃）什么都不通过。 这适用于与特定用户不对应的脱机进程。 例如，确定要存储在搜索
        索引中的价格。
    """

    def strategy(self, request=None, user=None, **kwargs):
        """
        Return an instanticated strategy instance
        返回一个即时策略实例
        """
        # Default to the backwards-compatible strategy of picking the first
        # stockrecord but charging zero tax.
        # 默认为向后兼容的策略，即选择第一个库存记录但收取零税。
        return Default(request)


class Base(object):
    """
    The base strategy class

    Given a product, strategies are responsible for returning a
    ``PurchaseInfo`` instance which contains:

    - The appropriate stockrecord for this customer
    - A pricing policy instance
    - An availability policy instance

    基础策略类
    给定一个产品，策略负责返回一个``PurchaseInfo``实例，该实例包含：
    - 该客户的适当库存记录
    - 定价政策实例
    - 可用性策略实例
    """

    def __init__(self, request=None):
        self.request = request
        self.user = None
        if request and request.user.is_authenticated:
            self.user = request.user

    def fetch_for_product(self, product, stockrecord=None):
        """
        Given a product, return a ``PurchaseInfo`` instance.

        The ``PurchaseInfo`` class is a named tuple with attributes:

        - ``price``: a pricing policy object.
        - ``availability``: an availability policy object.
        - ``stockrecord``: the stockrecord that is being used

        If a stockrecord is passed, return the appropriate ``PurchaseInfo``
        instance for that product and stockrecord is returned.

        给定一个产品，返回一个``PurchaseInfo``实例。
        ``PurchaseInfo``类是一个带有属性的命名元组：
        - ``price``：定价政策对象。
        - ``availability``：可用性策略对象。
        - ``stockrecord``：正在使用的库存记录
        """
        raise NotImplementedError(
            "A strategy class must define a fetch_for_product method "
            "for returning the availability and pricing "
            "information."
        )

    def fetch_for_parent(self, product):
        """
        Given a parent product, fetch a ``StockInfo`` instance
        给定父产品，获取``StockInfo``实例
        """
        raise NotImplementedError(
            "A strategy class must define a fetch_for_parent method "
            "for returning the availability and pricing "
            "information."
        )

    def fetch_for_line(self, line, stockrecord=None):
        """
        Given a basket line instance, fetch a ``PurchaseInfo`` instance.

        This method is provided to allow purchase info to be determined using a
        basket line's attributes.  For instance, "bundle" products often use
        basket line attributes to store SKUs of contained products.  For such
        products, we need to look at the availability of each contained product
        to determine overall availability.

        给定一个购物篮行实例，获取一个``PurchaseInfo``实例。
        提供此方法是为了允许使用篮子线的属性确定购买信息。 例如，“捆绑”产品通常
        使用篮子线属性来存储所包含产品的SKU。 对于此类产品，我们需要查看每个包含产
        品的可用性，以确定总体可用性。
        """
        # Default to ignoring any basket line options as we don't know what to
        # do with them within Oscar - that's up to your project to implement.
        # 默认忽略任何购物篮行选项，因为我们不知道如何在奥斯卡中使
        # 用它们 - 这取决于您的项目实施。
        return self.fetch_for_product(line.product)


class Structured(Base):
    """
    A strategy class which provides separate, overridable methods for
    determining the 3 things that a ``PurchaseInfo`` instance requires:

    #) A stockrecord
    #) A pricing policy
    #) An availability policy
    一个策略类，它提供单独的，可重写的方法，用于确定``PurchaseInfo``实例所
    需的3个内容：
    ＃）库存记录
    ＃）定价政策
    ＃）可用性策略
    """

    def fetch_for_product(self, product, stockrecord=None):
        """
        Return the appropriate ``PurchaseInfo`` instance.

        This method is not intended to be overridden.

        返回相应的``PurchaseInfo``实例。
        此方法无意被覆盖
        """
        if stockrecord is None:
            stockrecord = self.select_stockrecord(product)
        return PurchaseInfo(
            price=self.pricing_policy(product, stockrecord),
            availability=self.availability_policy(product, stockrecord),
            stockrecord=stockrecord)

    def fetch_for_parent(self, product):
        # Select children and associated stockrecords
        # 选择子产品和相关的库存记录
        children_stock = self.select_children_stockrecords(product)
        return PurchaseInfo(
            price=self.parent_pricing_policy(product, children_stock),
            availability=self.parent_availability_policy(
                product, children_stock),
            stockrecord=None)

    def select_stockrecord(self, product):
        """
        Select the appropriate stockrecord
        选择合适的库存记录
        """
        raise NotImplementedError(
            "A structured strategy class must define a "
            "'select_stockrecord' method")

    def select_children_stockrecords(self, product):
        """
        Select appropriate stock record for all children of a product
        为产品的所有子项选择适当的库存记录
        """
        records = []
        for child in product.children.all():
            # Use tuples of (child product, stockrecord)
            # 使用（子产品，库存记录）的元组
            records.append((child, self.select_stockrecord(child)))
        return records

    def pricing_policy(self, product, stockrecord):
        """
        Return the appropriate pricing policy
        返回适当的定价政策
        """
        raise NotImplementedError(
            "A structured strategy class must define a "
            "'pricing_policy' method")

    def parent_pricing_policy(self, product, children_stock):
        raise NotImplementedError(
            "A structured strategy class must define a "
            "'parent_pricing_policy' method")

    def availability_policy(self, product, stockrecord):
        """
        Return the appropriate availability policy
        返回适当的可用性策略
        """
        raise NotImplementedError(
            "A structured strategy class must define a "
            "'availability_policy' method")

    def parent_availability_policy(self, product, children_stock):
        raise NotImplementedError(
            "A structured strategy class must define a "
            "'parent_availability_policy' method")


# Mixins - these can be used to construct the appropriate strategy class
# 混入 - 这些可用于构建适当的策略类


class UseFirstStockRecord(object):
    """
    Stockrecord selection mixin for use with the ``Structured`` base strategy.
    This mixin picks the first (normally only) stockrecord to fulfil a product.

    This is backwards compatible with Oscar<0.6 where only one stockrecord per
    product was permitted.

    库存记录选择mixin与``Structured``基础策略一起使用。这个mixin选择第一个
    （通常只有）库存记录来实现产品。
    这与Oscar <0.6向后兼容，其中每个产品只允许一个库存记录。
    """

    def select_stockrecord(self, product):
        try:
            return product.stockrecords.all()[0]
        except IndexError:
            return None


class StockRequired(object):
    """
    Availability policy mixin for use with the ``Structured`` base strategy.
    This mixin ensures that a product can only be bought if it has stock
    available (if stock is being tracked).
    可用性策略mixin用于``Structured``基础策略。 这种mixin确保只有在有库存的
    情况下才能购买产品（如果有跟踪库存的话）。
    """

    def availability_policy(self, product, stockrecord):
        if not stockrecord:
            return Unavailable()
        if not product.get_product_class().track_stock:
            return Available()
        else:
            return StockRequiredAvailability(
                stockrecord.net_stock_level)

    def parent_availability_policy(self, product, children_stock):
        # A parent product is available if one of its children is
        # 如果其中一个子产品是父产品，则可以使用
        for child, stockrecord in children_stock:
            policy = self.availability_policy(product, stockrecord)
            if policy.is_available_to_buy:
                return Available()
        return Unavailable()


class NoTax(object):
    """
    Pricing policy mixin for use with the ``Structured`` base strategy.
    This mixin specifies zero tax and uses the ``price_excl_tax`` from the
    stockrecord.
    定价政策mixin与``Structured``基础策略一起使用。 这个mixin指定零税，
    并使用stockrecord中的``price_excl_tax``。
    """

    def pricing_policy(self, product, stockrecord):
        # Check stockrecord has the appropriate data
        # 检查库存记录是否有合适的数据
        if not stockrecord or stockrecord.price_excl_tax is None:
            return UnavailablePrice()
        return FixedPrice(
            currency=stockrecord.price_currency,
            excl_tax=stockrecord.price_excl_tax,
            tax=D('0.00'))

    def parent_pricing_policy(self, product, children_stock):
        stockrecords = [x[1] for x in children_stock if x[1] is not None]
        if not stockrecords:
            return UnavailablePrice()
        # We take price from first record
        # 我们从第一个记录中获取价格
        stockrecord = stockrecords[0]
        return FixedPrice(
            currency=stockrecord.price_currency,
            excl_tax=stockrecord.price_excl_tax,
            tax=D('0.00'))


class FixedRateTax(object):
    """
    Pricing policy mixin for use with the ``Structured`` base strategy.  This
    mixin applies a fixed rate tax to the base price from the product's
    stockrecord.  The price_incl_tax is quantized to two decimal places.
    Rounding behaviour is Decimal's default

    与“Structured(结构化)”基本策略一起使用的定价策略MIXIN。这种mixin法适用于从产品
    的库存记录中收取固定价格的基础税率。price_incl_tax被量化为两个小数点。
    舍入行为是十进制的默认值。
    """
    rate = D('0')  # Subclass and specify the correct rate 子类并指定正确率
    exponent = D('0.01')  # Default to two decimal places 默认为小数点后两位

    def pricing_policy(self, product, stockrecord):
        if not stockrecord or stockrecord.price_excl_tax is None:
            return UnavailablePrice()
        rate = self.get_rate(product, stockrecord)
        exponent = self.get_exponent(stockrecord)
        tax = (stockrecord.price_excl_tax * rate).quantize(exponent)
        return TaxInclusiveFixedPrice(
            currency=stockrecord.price_currency,
            excl_tax=stockrecord.price_excl_tax,
            tax=tax)

    def parent_pricing_policy(self, product, children_stock):
        stockrecords = [x[1] for x in children_stock if x[1] is not None]
        if not stockrecords:
            return UnavailablePrice()

        # We take price from first record 我们从第一次记录中取价
        stockrecord = stockrecords[0]
        rate = self.get_rate(product, stockrecord)
        exponent = self.get_exponent(stockrecord)
        tax = (stockrecord.price_excl_tax * rate).quantize(exponent)

        return FixedPrice(
            currency=stockrecord.price_currency,
            excl_tax=stockrecord.price_excl_tax,
            tax=tax)

    def get_rate(self, product, stockrecord):
        """
        This method serves as hook to be able to plug in support for varying tax rates
        based on the product.

        TODO: Needs tests.

        这种方法可以作为hook，以便能够根据产品插入对不同税率的支持。
        TODO:需要测试
        """
        return self.rate

    def get_exponent(self, stockrecord):
        """
        This method serves as hook to be able to plug in support for a varying exponent
        based on the currency.

        TODO: Needs tests.

        此方法用作hook，以便能够根据货币插入对变量指数的支持。
        TODO:需要测试
        """
        return self.exponent


class DeferredTax(object):
    """
    Pricing policy mixin for use with the ``Structured`` base strategy.
    This mixin does not specify the product tax and is suitable to territories
    where tax isn't known until late in the checkout process.
    定价政策mixin与``Structured``基础策略一起使用。
    此mixin不指定产品税，适用于在结账过程后期才知道税收的地区。
    """

    def pricing_policy(self, product, stockrecord):
        if not stockrecord or stockrecord.price_excl_tax is None:
            return UnavailablePrice()
        return FixedPrice(
            currency=stockrecord.price_currency,
            excl_tax=stockrecord.price_excl_tax)

    def parent_pricing_policy(self, product, children_stock):
        stockrecords = [x[1] for x in children_stock if x[1] is not None]
        if not stockrecords:
            return UnavailablePrice()

        # We take price from first record 我们从第一个记录中获取价格
        stockrecord = stockrecords[0]

        return FixedPrice(
            currency=stockrecord.price_currency,
            excl_tax=stockrecord.price_excl_tax)


# Example strategy composed of above mixins.  For real projects, it's likely
# you'll want to use a different pricing mixin as you'll probably want to
# charge tax!
# 由上述mixins组成的示例策略。 对于真实的项目，你很可能想要使用不同的定价
# 组合，因为你可能想要征税！


class Default(UseFirstStockRecord, StockRequired, NoTax, Structured):
    """
    Default stock/price strategy that uses the first found stockrecord for a
    product, ensures that stock is available (unless the product class
    indicates that we don't need to track stock) and charges zero tax.
    使用产品的第一个找到的库存记录的默认库存/价格策略，确保库存可用（除非产品
    类别表明我们不需要跟踪库存）并收取零税。
    """


class UK(UseFirstStockRecord, StockRequired, FixedRateTax, Structured):
    """
    Sample strategy for the UK that:

    - uses the first stockrecord for each product (effectively assuming
        there is only one).
    - requires that a product has stock available to be bought
    - applies a fixed rate of tax on all products

    This is just a sample strategy used for internal development.  It is not
    recommended to be used in production, especially as the tax rate is
    hard-coded.

    英国的样本策略：
    - 为每种产品使用第一个库存记录（实际上假设只有一个）。
    - 要求产品有库存可供购买
    - 对所有产品适用固定税率
    这只是用于内部开发的示例策略。 不建议在生产中使用，特别是因为税率是硬编码的。
    """
    # Use UK VAT rate (as of December 2013)
    # 使用英国增值税税率（截至2013年12月）
    rate = D('0.20')


class US(UseFirstStockRecord, StockRequired, DeferredTax, Structured):
    """
    Sample strategy for the US.

    - uses the first stockrecord for each product (effectively assuming
      there is only one).
    - requires that a product has stock available to be bought
    - doesn't apply a tax to product prices (normally this will be done
      after the shipping address is entered).

    This is just a sample one used for internal development.  It is not
    recommended to be used in production.

    美国的样本策略。
    - 为每种产品使用第一个库存记录（实际上假设只有一个）。
    - 要求产品有库存可供购买
    - 不对产品价格征税（通常这将在输入送货地址后完成）。

    这只是用于内部开发的样本。 不建议在生产中使用。
    """
