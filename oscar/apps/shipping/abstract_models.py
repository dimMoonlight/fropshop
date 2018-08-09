# -*- coding: utf-8 -*-
from decimal import Decimal as D

from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from oscar.core import loading, prices
from oscar.models.fields import AutoSlugField

Scale = loading.get_class('shipping.scales', 'Scale')


class AbstractBase(models.Model):
    """
    Implements the interface declared by shipping.base.Base
    实现shipping.base.Base声明的接口
    """
    code = AutoSlugField(_("Slug"), max_length=128, unique=True,
                         populate_from='name')
    name = models.CharField(_("Name"), max_length=128, unique=True)
    description = models.TextField(_("Description"), blank=True)

    # We allow shipping methods to be linked to a specific set of countries
    # 我们允许将运输方法链接到特定的一组国家。
    countries = models.ManyToManyField('address.Country',
                                       blank=True, verbose_name=_("Countries"))

    # We need this to mimic the interface of the Base shipping method
    # 我们需要这个来模仿Base运输方法的界面
    is_discounted = False

    class Meta:
        abstract = True
        app_label = 'shipping'
        ordering = ['name']
        verbose_name = _("Shipping Method")
        verbose_name_plural = _("Shipping Methods")

    def __str__(self):
        return self.name

    def discount(self, basket):
        """
        Return the discount on the standard shipping charge
        退还标准运费的折扣
        """
        # This method is identical to the Base.discount().
        return D('0.00')


class AbstractOrderAndItemCharges(AbstractBase):
    """
    Standard shipping method

    This method has two components:
    * a charge per order
    * a charge per item

    Many sites use shipping logic which fits into this system.  However, for
    more complex shipping logic, a custom shipping method object will need to
    be provided that subclasses ShippingMethod.

    标准送货方式
    这种方法有两个组成部分：
    * 每个订单收费
    * 每件商品的费用

    许多站点使用适合此系统的运输逻辑。 但是，对于更复杂的装运逻辑，需要提供
    子类ShippingMethod的自定义装运方法对象。
    """
    price_per_order = models.DecimalField(
        _("Price per order"), decimal_places=2, max_digits=12,
        default=D('0.00'))
    price_per_item = models.DecimalField(
        _("Price per item"), decimal_places=2, max_digits=12,
        default=D('0.00'))

    # If basket value is above this threshold, then shipping is free
    # 如果购物篮价值高于此阈值，那么运费是免费的
    free_shipping_threshold = models.DecimalField(
        _("Free Shipping"), decimal_places=2, max_digits=12, blank=True,
        null=True)

    class Meta(AbstractBase.Meta):
        abstract = True
        app_label = 'shipping'
        verbose_name = _("Order and Item Charge")
        verbose_name_plural = _("Order and Item Charges")

    def calculate(self, basket):
        if (self.free_shipping_threshold is not None and
                basket.total_incl_tax >= self.free_shipping_threshold):
            return prices.Price(
                currency=basket.currency, excl_tax=D('0.00'),
                incl_tax=D('0.00'))

        charge = self.price_per_order
        for line in basket.lines.all():
            if line.product.is_shipping_required:
                charge += line.quantity * self.price_per_item

        # Zero tax is assumed...
        # 假设零税率…
        return prices.Price(
            currency=basket.currency,
            excl_tax=charge,
            incl_tax=charge)


class AbstractWeightBased(AbstractBase):
    # The attribute code to use to look up the weight of a product
    # 用于查找产品重量的属性代码
    weight_attribute = 'weight'

    # The default weight to use (in kg) when a product doesn't have a weight
    # attribute.
    # 当产品没有权重属性时使用的缺省权重（kg）。
    default_weight = models.DecimalField(
        _("Default Weight"), decimal_places=3, max_digits=12,
        default=D('0.000'),
        validators=[MinValueValidator(D('0.00'))],
        help_text=_("Default product weight in kg when no weight attribute "
                    "is defined"))

    class Meta(AbstractBase.Meta):
        abstract = True
        app_label = 'shipping'
        verbose_name = _("Weight-based Shipping Method")
        verbose_name_plural = _("Weight-based Shipping Methods")

    def calculate(self, basket):
        # Note, when weighing the basket, we don't check whether the item
        # requires shipping or not.  It is assumed that if something has a
        # weight, then it requires shipping.
        # 注意，当称重购物篮时，我们不检查物品是否需要运输。假设如果某物
        # 有重量，则需要运输。
        scale = Scale(attribute_code=self.weight_attribute,
                      default_weight=self.default_weight)
        weight = scale.weigh_basket(basket)
        charge = self.get_charge(weight)

        # Zero tax is assumed...
        # 假设零税率…
        return prices.Price(
            currency=basket.currency,
            excl_tax=charge,
            incl_tax=charge)

    def get_charge(self, weight):
        """
        Calculates shipping charges for a given weight.

        If there is one or more matching weight band for a given weight, the
        charge of the closest matching weight band is returned.

        If the weight exceeds the top weight band, the top weight band charge
        is added until a matching weight band is found. This models the concept
        of "sending as many of the large boxes as needed".

        Please note that it is assumed that the closest matching weight band
        is the most cost-effective one, and that the top weight band is more
        cost effective than e.g. sending out two smaller parcels.
        Without that assumption, determining the cheapest shipping solution
        becomes an instance of the bin packing problem. The bin packing problem
        is NP-hard and solving it is left as an exercise to the reader.

        计算给定重量的运费。
        如果给定重量存在一个或多个匹配的重量带，则返回最接近的匹配重量带的费用。
        如果重量超过最大重量带，则添加顶部重量带电荷直到找到匹配的重量带。 这模拟
        了“根据需要发送尽可能多的大盒子”的概念。
        请注意，假设最接近的匹配重量带是最具成本效益的重量带，并且顶部重量带比例
        如成本效率更高。 寄出两个较小的包裹。
        没有这种假设，确定最便宜的运输解决方案就成了垃圾箱包装问题的一个例子。
        垃圾箱包装问题是NP难的，解决它是留给读者的练习。
        """
        weight = D(weight)  # weight really should be stored as a decimal 重量确实应该存储为小数
        if not self.bands.exists():
            return D('0.00')

        top_band = self.top_band
        if weight < top_band.upper_limit:
            band = self.get_band_for_weight(weight)
            return band.charge
        else:
            quotient, remaining_weight = divmod(weight, top_band.upper_limit)
            remainder_band = self.get_band_for_weight(remaining_weight)
            return quotient * top_band.charge + remainder_band.charge

    def get_band_for_weight(self, weight):
        """
        Return the closest matching weight band for a given weight.
        返回给定重量的最接近的匹配重量带。
        """
        try:
            return self.bands.filter(
                upper_limit__gte=weight).order_by('upper_limit')[0]
        except IndexError:
            return None

    @property
    def num_bands(self):
        return self.bands.count()

    @property
    def top_band(self):
        try:
            return self.bands.order_by('-upper_limit')[0]
        except IndexError:
            return None


class AbstractWeightBand(models.Model):
    """
    Represents a weight band which are used by the WeightBasedShipping method.
    表示WeightBasedShipping方法使用的权重带。
    """
    method = models.ForeignKey(
        'shipping.WeightBased',
        on_delete=models.CASCADE,
        related_name='bands',
        verbose_name=_("Method"))
    upper_limit = models.DecimalField(
        _("Upper Limit"), decimal_places=3, max_digits=12,
        validators=[MinValueValidator(D('0.00'))],
        help_text=_("Enter upper limit of this weight band in kg. The lower "
                    "limit will be determined by the other weight bands."))
    charge = models.DecimalField(
        _("Charge"), decimal_places=2, max_digits=12,
        validators=[MinValueValidator(D('0.00'))])

    @property
    def weight_from(self):
        lower_bands = self.method.bands.filter(
            upper_limit__lt=self.upper_limit).order_by('-upper_limit')
        if not lower_bands:
            return D('0.000')
        return lower_bands[0].upper_limit

    @property
    def weight_to(self):
        return self.upper_limit

    class Meta:
        abstract = True
        app_label = 'shipping'
        ordering = ['method', 'upper_limit']
        verbose_name = _("Weight Band")
        verbose_name_plural = _("Weight Bands")

    def __str__(self):
        return _('Charge for weights up to %s kg') % (self.upper_limit,)
