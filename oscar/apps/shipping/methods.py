from decimal import Decimal as D

from django.utils.translation import gettext_lazy as _

from oscar.core import prices


class Base(object):
    """
    Shipping method interface class

    This is the superclass to the classes in methods.py, and a de-facto
    superclass to the classes in models.py. This allows using all
    shipping methods interchangeably (aka polymorphism).

    The interface is all properties.

    送货方法接口类
    这是methods.py中类的超类，以及models.py中类的事实上的超类。 这允许可互
    换地使用所有运输方法（也称为多态）。
    界面是所有属性。
    """

    #: Used to store this method in the session.  Each shipping method should
    #  have a unique code.
    # 用于在会话中存储此方法。 每种送货方式都应该有唯一的代码。
    code = '__default__'

    #: The name of the shipping method, shown to the customer during checkout
    # 在结账时向客户显示的送货方式的名称
    name = 'Default shipping'

    #: A more detailed description of the shipping method shown to the customer
    #  during checkout.  Can contain HTML.
    # 结账时向客户显示的送货方式的更详细说明。 可以包含HTML。
    description = ''

    #: Whether the charge includes a discount
    # 费用是否包含折扣
    is_discounted = False

    def calculate(self, basket):
        """
        Return the shipping charge for the given basket
        退还给定购物篮的运费
        """
        raise NotImplemented()

    def discount(self, basket):
        """
        Return the discount on the standard shipping charge
        退还标准运费的折扣
        """
        # The regular shipping methods don't add a default discount.
        # For offers and vouchers, the discount will be provided
        # by a wrapper that Repository.apply_shipping_offer() adds.
        # 常规送货方式不会添加默认折扣。
        # 对于优惠和优惠券，酒店将提供折扣优惠
        # 通过Repository.apply_shipping_offer（）添加的包装器。
        return D('0.00')


class Free(Base):
    """
    This shipping method specifies that shipping is free.
    此送货方式指定送货是免费的
    """
    code = 'free-shipping'
    name = _('Free shipping')

    def calculate(self, basket):
        # If the charge is free then tax must be free (musn't it?) and so we
        # immediately set the tax to zero
        # 如果收费是免费的，那么税收必须是免费的（不是吗？）因此我们立即将税收设定为零
        return prices.Price(
            currency=basket.currency,
            excl_tax=D('0.00'), tax=D('0.00'))


class NoShippingRequired(Free):
    """
    This is a special shipping method that indicates that no shipping is
    actually required (eg for digital goods).
    这是一种特殊的运输方式，表明实际上不需要运输（例如，对于数字商品）。
    """
    code = 'no-shipping-required'
    name = _('No shipping required')


class FixedPrice(Base):
    """
    This shipping method indicates that shipping costs a fixed price and
    requires no special calculation.
    此运输方式表明运费是固定价格，无需特殊计算。
    """
    code = 'fixed-price-shipping'
    name = _('Fixed price shipping')

    # Charges can be either declared by subclassing and overriding the
    # class attributes or by passing them to the constructor
    # 可以通过子类化和覆盖类属性或通过将它们传递给构造函数来声明费用
    charge_excl_tax = None
    charge_incl_tax = None

    def __init__(self, charge_excl_tax=None, charge_incl_tax=None):
        if charge_excl_tax is not None:
            self.charge_excl_tax = charge_excl_tax
        if charge_incl_tax is not None:
            self.charge_incl_tax = charge_incl_tax

    def calculate(self, basket):
        return prices.Price(
            currency=basket.currency,
            excl_tax=self.charge_excl_tax,
            incl_tax=self.charge_incl_tax)


class OfferDiscount(Base):
    """
    Wrapper class that applies a discount to an existing shipping
    method's charges.
    包装类，对现有送货方式的费用应用折扣。
    """
    is_discounted = True

    def __init__(self, method, offer):
        self.method = method
        self.offer = offer

    # Forwarded properties 转发的财产

    @property
    def code(self):
        return self.method.code

    @property
    def name(self):
        return self.method.name

    @property
    def discount_name(self):
        return self.offer.name

    @property
    def description(self):
        return self.method.description

    def calculate_excl_discount(self, basket):
        return self.method.calculate(basket)


class TaxExclusiveOfferDiscount(OfferDiscount):
    """
    Wrapper class which extends OfferDiscount to be exclusive of tax.
    将OfferDiscount扩展为包含税的包装类。
    """

    def calculate(self, basket):
        base_charge = self.method.calculate(basket)
        discount = self.offer.shipping_discount(base_charge.excl_tax)
        excl_tax = base_charge.excl_tax - discount
        return prices.Price(
            currency=base_charge.currency,
            excl_tax=excl_tax)

    def discount(self, basket):
        base_charge = self.method.calculate(basket)
        return self.offer.shipping_discount(base_charge.excl_tax)


class TaxInclusiveOfferDiscount(OfferDiscount):
    """
    Wrapper class which extends OfferDiscount to be inclusive of tax.
    包装类，它将OfferDiscount扩展为包含税。
    """

    def calculate(self, basket):
        base_charge = self.method.calculate(basket)
        discount = self.offer.shipping_discount(base_charge.incl_tax)
        incl_tax = base_charge.incl_tax - discount
        excl_tax = self.calculate_excl_tax(base_charge, incl_tax)
        return prices.Price(
            currency=base_charge.currency,
            excl_tax=excl_tax, incl_tax=incl_tax)

    def calculate_excl_tax(self, base_charge, incl_tax):
        """
        Return the charge excluding tax (but including discount).
        退还不含税的费用（但包括折扣）。
        """
        if incl_tax == D('0.00'):
            return D('0.00')
        # We assume we can linearly scale down the excl tax price before
        # discount.
        # 我们假设我们可以在折扣前线性降低excl税价。
        excl_tax = base_charge.excl_tax * (
            incl_tax / base_charge.incl_tax)
        return excl_tax.quantize(D('0.01'))

    def discount(self, basket):
        base_charge = self.method.calculate(basket)
        return self.offer.shipping_discount(base_charge.incl_tax)
