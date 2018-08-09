from oscar.core import prices


class Base(object):
    """
    The interface that any pricing policy must support
    任何定价政策必须支持的界面
    """

    #: Whether any prices exist
    # 是否存在任何价格
    exists = False

    #: Whether tax is known
    # 是否已知税收
    is_tax_known = False

    #: Price excluding tax
    # 不含税的价格
    excl_tax = None

    #: Price including tax
    # 价格含税
    incl_tax = None

    #: Price to use for offer calculations
    # 要用于报价计算的价格
    @property
    def effective_price(self):
        # Default to using the price excluding tax for calculations
        # 默认使用不含税的价格进行计算
        return self.excl_tax

    #: Price tax 价格税
    tax = None

    #: Retail price 零售价
    retail = None

    #: Price currency (3 char code) 价格货币（3个字符代码）
    currency = None

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self.__dict__)


class Unavailable(Base):
    """
    This should be used as a pricing policy when a product is unavailable and
    no prices are known.
    当产品不可用且没有价格时，这应该用作定价政策。
    """


class FixedPrice(Base):
    """
    This should be used for when the price of a product is known in advance.

    It can work for when tax isn't known (like in the US).

    Note that this price class uses the tax-exclusive price for offers, even if
    the tax is known.  This may not be what you want.  Use the
    TaxInclusiveFixedPrice class if you want offers to use tax-inclusive
    prices.

    这应该用于预先知道产品价格的情况。
    它可以用于何时不知道税收（如在美国）。
    请注意，即使税已知，此价格类也会使用报价的独占税。 这可能不是你想要的。
    如果您希望报价使用含税价格，请使用TaxInclusiveFixedPrice类。
    """
    exists = True

    def __init__(self, currency, excl_tax, tax=None):
        self.currency = currency
        self.excl_tax = excl_tax
        self.tax = tax

    @property
    def incl_tax(self):
        if self.is_tax_known:
            return self.excl_tax + self.tax
        raise prices.TaxNotKnown(
            "Can't calculate price.incl_tax as tax isn't known")

    @property
    def is_tax_known(self):
        return self.tax is not None


class TaxInclusiveFixedPrice(FixedPrice):
    """
    Specialised version of FixedPrice that must have tax passed.  It also
    specifies that offers should use the tax-inclusive price (which is the norm
    in the UK).
    必须征税的FixedPrice专业版。 它还规定要约应使用含税价格（这是英国的标准）。
    """
    exists = is_tax_known = True

    def __init__(self, currency, excl_tax, tax):
        self.currency = currency
        self.excl_tax = excl_tax
        self.tax = tax

    @property
    def incl_tax(self):
        return self.excl_tax + self.tax

    @property
    def effective_price(self):
        return self.incl_tax
