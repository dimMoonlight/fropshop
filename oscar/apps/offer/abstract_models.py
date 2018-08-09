import itertools
import operator
import os
import re
from decimal import Decimal as D
from decimal import ROUND_DOWN

from django.conf import settings
from django.core import exceptions
from django.db import models
from django.db.models.query import Q
from django.template.defaultfilters import date as date_filter
from django.urls import reverse
from django.utils.functional import cached_property
from django.utils.timezone import get_current_timezone, now
from django.utils.translation import gettext_lazy as _

from oscar.core.compat import AUTH_USER_MODEL
from oscar.core.loading import get_class, get_classes, get_model
from oscar.models import fields
from oscar.templatetags.currency_filters import currency

ActiveOfferManager, BrowsableRangeManager \
    = get_classes('offer.managers', ['ActiveOfferManager', 'BrowsableRangeManager'])
ZERO_DISCOUNT = get_class('offer.results', 'ZERO_DISCOUNT')
load_proxy, unit_price = get_classes('offer.utils', ['load_proxy', 'unit_price'])


# 基本报价
class BaseOfferMixin(models.Model):
    class Meta:
        abstract = True

    def proxy(self):
        """
        Return the proxy model
        返回代理模型
        """
        klassmap = self.proxy_map
        # Short-circuit logic if current class is already a proxy class.
        # 如果当前类已经是代理类，则为缩短逻辑。
        if self.__class__ in klassmap.values():
            return self

        field_dict = dict(self.__dict__)
        for field in list(field_dict.keys()):
            if field.startswith('_'):
                del field_dict[field]

        if self.proxy_class:
            klass = load_proxy(self.proxy_class)
            # Short-circuit again.
            # 再次缩短
            if self.__class__ == klass:
                return self
            return klass(**field_dict)
        if self.type in klassmap:
            return klassmap[self.type](**field_dict)
        raise RuntimeError("Unrecognised %s type (%s)" % (self.__class__.__name__.lower(), self.type))

    def __str__(self):
        return self.name

    @property
    def name(self):
        """
        A plaintext description of the benefit/condition. Every proxy class
        has to implement it.

        This is used in the dropdowns within the offer dashboard.

        利益/条件的明文描述。 每个代理类都必须实现它。
        这用于商品信息中心内的下拉菜单。
        """
        proxy_instance = self.proxy()
        if self.proxy_class and self.__class__ == proxy_instance.__class__:
            raise AssertionError('Name property is not defined on proxy class.')
        return proxy_instance.name

    @property
    def description(self):
        """
        A description of the benefit/condition.
        Defaults to the name. May contain HTML.
        利益/条件的明文描述。 默认为名称。 可能包含HTML。
        """
        return self.name


# 抽象条件报价
class AbstractConditionalOffer(models.Model):
    """
    A conditional offer (eg buy 1, get 10% off)
    有条件的报价（例如买1，获得10％的折扣）
    """
    name = models.CharField(
        _("Name"), max_length=128, unique=True,
        help_text=_("This is displayed within the customer's basket"))
    # 这陈列在顾客的购物篮里。
    slug = fields.AutoSlugField(
        _("Slug"), max_length=128, unique=True, populate_from='name')
    description = models.TextField(_("Description"), blank=True,
                                   help_text=_("This is displayed on the offer"
                                               " browsing page"))
    # 这将陈列在报价浏览页面上。

    # Offers come in a few different types:
    # (a) Offers that are available to all customers on the site.  Eg a
    #     3-for-2 offer.
    # (b) Offers that are linked to a voucher, and only become available once
    #     that voucher has been applied to the basket
    # (c) Offers that are linked to a user.  Eg, all students get 10% off.  The
    #     code to apply this offer needs to be coded
    # (d) Session offers - these are temporarily available to a user after some
    #     trigger event.  Eg, users coming from some affiliate site get 10%
    #     off.

    # 报价有几种不同的类型：
    # （a）提供给网站上所有客户的报价。3比2报价。
    # （b）与优惠券相关联的报价，只有在优惠券适用于购物篮后才可使用
    # （c）与用户相关的报价。 例如，所有学生都可享受10％的折扣。 需要对应用此报价
    #      的代码进行编码
    # （d）会话提供 - 在某些触发事件之后，这些提供暂时可供用户使用。 例如，来自某
    #      个联盟网站的用户可获得10％的折扣。
    SITE, VOUCHER, USER, SESSION = ("Site", "Voucher", "User", "Session")
    TYPE_CHOICES = (
        (SITE, _("Site offer - available to all users")),
        (VOUCHER, _("Voucher offer - only available after entering "
                    "the appropriate voucher code")),
        (USER, _("User offer - available to certain types of user")),
        (SESSION, _("Session offer - temporary offer, available for "
                    "a user for the duration of their session")),
    )
    offer_type = models.CharField(
        _("Type"), choices=TYPE_CHOICES, default=SITE, max_length=128)

    exclusive = models.BooleanField(
        _("Exclusive offer"),
        help_text=_("Exclusive offers cannot be combined on the same items"),
        # 独家报价不能组合在同一项目上
        default=True
    )

    # We track a status variable so it's easier to load offers that are
    # 'available' in some sense.
    # 我们跟踪状态变量，因此在某种意义上加载“可用”的商品更容易。
    OPEN, SUSPENDED, CONSUMED = "Open", "Suspended", "Consumed"
    status = models.CharField(_("Status"), max_length=64, default=OPEN)

    condition = models.ForeignKey(
        'offer.Condition',
        on_delete=models.CASCADE,
        related_name='offers',
        verbose_name=_("Condition"))
    benefit = models.ForeignKey(
        'offer.Benefit',
        on_delete=models.CASCADE,
        related_name='offers',
        verbose_name=_("Benefit"))

    # Some complicated situations require offers to be applied in a set order.
    # 某些复杂情况需要按订单顺序应用商品。
    priority = models.IntegerField(
        _("Priority"), default=0,
        help_text=_("The highest priority offers are applied first"))
    # 首先应用优先级最高的报价

    # AVAILABILITY 可用性

    # Range of availability.  Note that if this is a voucher offer, then these
    # dates are ignored and only the dates from the voucher are used to
    # determine availability.
    # 可用范围。 请注意，如果这是优惠券报价，则会忽略这些日期，并且仅使用优惠
    # 券中的日期来确定可用性。
    start_datetime = models.DateTimeField(
        _("Start date"), blank=True, null=True,
        help_text=_("Offers are active from the start date. "
                    "Leave this empty if the offer has no start date."))
    # 报价从开始日期起生效，如果报价没有开始日期，则空。
    end_datetime = models.DateTimeField(
        _("End date"), blank=True, null=True,
        help_text=_("Offers are active until the end date. "
                    "Leave this empty if the offer has no expiry date."))
    # 报价一直有效到截止日期为止。如果报价没有到期日，请保留此空白。

    # Use this field to limit the number of times this offer can be applied in
    # total.  Note that a single order can apply an offer multiple times so
    # this is not necessarily the same as the number of orders that can use it.
    # Also see max_basket_applications.
    # 使用此字段可限制此要约的总计应用次数。 请注意，单个订单可以多次应用要约，
    # 因此这不一定与可以使用它的订单数量相同。 另请参见max_basket_applications。
    max_global_applications = models.PositiveIntegerField(
        _("Max global applications"),
        help_text=_("The number of times this offer can be used before it "
                    "is unavailable"), blank=True, null=True)
    # 在不可用之前，可以使用该报价的次数。

    # Use this field to limit the number of times this offer can be used by a
    # single user.  This only works for signed-in users - it doesn't really
    # make sense for sites that allow anonymous checkout.
    # 使用此字段可限制单个用户可以使用此优惠的次数。 这仅适用于已登录的用户 - 对于允许
    # 匿名结帐的网站而言，它实际上没有意义。
    max_user_applications = models.PositiveIntegerField(
        _("Max user applications"),
        help_text=_("The number of times a single user can use this offer"),
        # 单个用户可以使用此优惠的次数
        blank=True, null=True)

    # Use this field to limit the number of times this offer can be applied to
    # a basket (and hence a single order). Often, an offer should only be
    # usable once per basket/order, so this field will commonly be set to 1.
    # 使用此字段可限制此优惠可应用于购物篮的次数（因此也可以是单个订单）。 通常，
    # 报价每个购物篮/订单只能使用一次，因此该字段通常设置为1。
    max_basket_applications = models.PositiveIntegerField(
        _("Max basket applications"),
        blank=True, null=True,
        help_text=_("The number of times this offer can be applied to a "
                    "basket (and order)"))
    # 此优惠可应用于购物篮（和订单）的次数

    # Use this field to limit the amount of discount an offer can lead to.
    # This can be helpful with budgeting.
    # 使用此字段可限制要约可能带来的折扣金额。 这对预算编制很有帮助。
    max_discount = models.DecimalField(
        _("Max discount"), decimal_places=2, max_digits=12, null=True,
        blank=True,
        help_text=_("When an offer has given more discount to orders "
                    "than this threshold, then the offer becomes "
                    "unavailable"))
    # 当报价给订单的折扣超过此阈值时，报价就会变得不可用

    # TRACKING 跟踪
    # These fields are used to enforce the limits set by the
    # max_* fields above.
    # 这些字段用于强制执行上述max_ *字段设置的限制。

    total_discount = models.DecimalField(
        _("Total Discount"), decimal_places=2, max_digits=12,
        default=D('0.00'))
    num_applications = models.PositiveIntegerField(
        _("Number of applications"), default=0)
    num_orders = models.PositiveIntegerField(
        _("Number of Orders"), default=0)

    redirect_url = fields.ExtendedURLField(
        _("URL redirect (optional)"), blank=True)
    date_created = models.DateTimeField(_("Date Created"), auto_now_add=True)

    objects = models.Manager()
    active = ActiveOfferManager()

    # We need to track the voucher that this offer came from (if it is a
    # voucher offer)
    # 我们需要跟踪此优惠来自的优惠券（如果是优惠券优惠）
    _voucher = None

    class Meta:
        abstract = True
        app_label = 'offer'
        ordering = ['-priority', 'pk']
        verbose_name = _("Conditional offer")
        verbose_name_plural = _("Conditional offers")

    def save(self, *args, **kwargs):
        # Check to see if consumption thresholds have been broken
        # 检查消耗阈值是否已被破坏
        if not self.is_suspended:
            if self.get_max_applications() == 0:
                self.status = self.CONSUMED
            else:
                self.status = self.OPEN

        return super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('offer:detail', kwargs={'slug': self.slug})

    def __str__(self):
        return self.name

    def clean(self):
        if (self.start_datetime and self.end_datetime and
                self.start_datetime > self.end_datetime):
            raise exceptions.ValidationError(
                _('End date should be later than start date'))

    @property
    def is_open(self):
        return self.status == self.OPEN

    @property
    def is_suspended(self):
        return self.status == self.SUSPENDED

    def suspend(self):
        self.status = self.SUSPENDED
        self.save()
    suspend.alters_data = True

    def unsuspend(self):
        self.status = self.OPEN
        self.save()
    unsuspend.alters_data = True

    def is_available(self, user=None, test_date=None):
        """
        Test whether this offer is available to be used
        测试是否可以使用此优惠
        """
        if self.is_suspended:
            return False
        if test_date is None:
            test_date = now()
        predicates = []
        if self.start_datetime:
            predicates.append(self.start_datetime > test_date)
        if self.end_datetime:
            predicates.append(test_date > self.end_datetime)
        if any(predicates):
            return False
        return self.get_max_applications(user) > 0

    def is_condition_satisfied(self, basket):
        return self.condition.proxy().is_satisfied(self, basket)

    def is_condition_partially_satisfied(self, basket):
        return self.condition.proxy().is_partially_satisfied(self, basket)

    def get_upsell_message(self, basket):
        return self.condition.proxy().get_upsell_message(self, basket)

    def apply_benefit(self, basket):
        """
        Applies the benefit to the given basket and returns the discount.
        将收益应用于给定的购物篮并返回折扣。
        """
        if not self.is_condition_satisfied(basket):
            return ZERO_DISCOUNT
        return self.benefit.proxy().apply(
            basket, self.condition.proxy(), self)

    def apply_deferred_benefit(self, basket, order, application):
        """
        Applies any deferred benefits.  These are things like adding loyalty
        points to someone's account.
        适用任何递延利益。 这些是将忠诚度积分添加到某人的帐户。
        """
        return self.benefit.proxy().apply_deferred(basket, order, application)

    def set_voucher(self, voucher):
        self._voucher = voucher

    def get_voucher(self):
        return self._voucher

    def get_max_applications(self, user=None):
        """
        Return the number of times this offer can be applied to a basket for a
        given user.
        返回此优惠可应用于给定用户的购物篮的次数。
        """
        if self.max_discount and self.total_discount >= self.max_discount:
            return 0

        # Hard-code a maximum value as we need some sensible upper limit for
        # when there are not other caps.
        # 硬编码最大值，因为当没有其他上限时我们需要一些合理的上限。
        limits = [10000]
        if self.max_user_applications and user:
            limits.append(max(0, self.max_user_applications -
                          self.get_num_user_applications(user)))
        if self.max_basket_applications:
            limits.append(self.max_basket_applications)
        if self.max_global_applications:
            limits.append(
                max(0, self.max_global_applications - self.num_applications))
        return min(limits)

    def get_num_user_applications(self, user):
        OrderDiscount = get_model('order', 'OrderDiscount')
        aggregates = OrderDiscount.objects.filter(offer_id=self.id,
                                                  order__user=user)\
            .aggregate(total=models.Sum('frequency'))
        return aggregates['total'] if aggregates['total'] is not None else 0

    def shipping_discount(self, charge):
        return self.benefit.proxy().shipping_discount(charge)

    def record_usage(self, discount):
        self.num_applications += discount['freq']
        self.total_discount += discount['discount']
        self.num_orders += 1
        self.save()
    record_usage.alters_data = True

    def availability_description(self):
        """
        Return a description of when this offer is available
        返回此优惠何时可用的说明
        """
        restrictions = self.availability_restrictions()
        descriptions = [r['description'] for r in restrictions]
        return "<br/>".join(descriptions)

    # 可用性限制
    def availability_restrictions(self):  # noqa (too complex (15))
        restrictions = []
        if self.is_suspended:
            restrictions.append({
                'description': _("Offer is suspended"),
                'is_satisfied': False})

        if self.max_global_applications:
            remaining = self.max_global_applications - self.num_applications
            desc = _("Limited to %(total)d uses (%(remainder)d remaining)") \
                % {'total': self.max_global_applications,
                   'remainder': remaining}
            restrictions.append({'description': desc,
                                 'is_satisfied': remaining > 0})

        if self.max_user_applications:
            if self.max_user_applications == 1:
                desc = _("Limited to 1 use per user")
            else:
                desc = _("Limited to %(total)d uses per user") \
                    % {'total': self.max_user_applications}
            restrictions.append({'description': desc,
                                 'is_satisfied': True})

        if self.max_basket_applications:
            if self.max_user_applications == 1:
                desc = _("Limited to 1 use per basket")
            else:
                desc = _("Limited to %(total)d uses per basket") \
                    % {'total': self.max_basket_applications}
            restrictions.append({
                'description': desc,
                'is_satisfied': True})

        def hide_time_if_zero(dt):
            # Only show hours/minutes if they have been specified
            # 仅显示小时/分钟（如果已指定）
            if dt.tzinfo:
                localtime = dt.astimezone(get_current_timezone())
            else:
                localtime = dt
            if localtime.hour == 0 and localtime.minute == 0:
                return date_filter(localtime, settings.DATE_FORMAT)
            return date_filter(localtime, settings.DATETIME_FORMAT)

        if self.start_datetime or self.end_datetime:
            today = now()
            if self.start_datetime and self.end_datetime:
                desc = _("Available between %(start)s and %(end)s") \
                    % {'start': hide_time_if_zero(self.start_datetime),
                       'end': hide_time_if_zero(self.end_datetime)}
                is_satisfied \
                    = self.start_datetime <= today <= self.end_datetime
            elif self.start_datetime:
                desc = _("Available from %(start)s") % {
                    'start': hide_time_if_zero(self.start_datetime)}
                is_satisfied = today >= self.start_datetime
            elif self.end_datetime:
                desc = _("Available until %(end)s") % {
                    'end': hide_time_if_zero(self.end_datetime)}
                is_satisfied = today <= self.end_datetime
            restrictions.append({
                'description': desc,
                'is_satisfied': is_satisfied})

        if self.max_discount:
            desc = _("Limited to a cost of %(max)s") % {
                'max': currency(self.max_discount)}
            restrictions.append({
                'description': desc,
                'is_satisfied': self.total_discount < self.max_discount})

        return restrictions

    @property
    def has_products(self):
        return self.condition.range is not None

    def products(self):
        """
        Return a queryset of products in this offer
        返回此优惠中的产品查询集
        """
        Product = get_model('catalogue', 'Product')
        if not self.has_products:
            return Product.objects.none()

        cond_range = self.condition.range
        if cond_range.includes_all_products:
            # Return ALL the products
            # 退回所有产品
            queryset = Product.browsable
        else:
            queryset = cond_range.all_products()
        return queryset.filter(is_discountable=True).exclude(
            structure=Product.CHILD)


# 抽象效益
class AbstractBenefit(BaseOfferMixin, models.Model):
    range = models.ForeignKey(
        'offer.Range',
        blank=True,
        null=True,
        on_delete=models.CASCADE,
        verbose_name=_("Range"))

    # Benefit types 利益类型
    PERCENTAGE, FIXED, MULTIBUY, FIXED_PRICE = (
        "Percentage", "Absolute", "Multibuy", "Fixed price")
    SHIPPING_PERCENTAGE, SHIPPING_ABSOLUTE, SHIPPING_FIXED_PRICE = (
        'Shipping percentage', 'Shipping absolute', 'Shipping fixed price')
    TYPE_CHOICES = (
        (PERCENTAGE, _("Discount is a percentage off of the product's value")),
        (FIXED, _("Discount is a fixed amount off of the product's value")),
        (MULTIBUY, _("Discount is to give the cheapest product for free")),
        (FIXED_PRICE,
         _("Get the products that meet the condition for a fixed price")),
        (SHIPPING_ABSOLUTE,
         _("Discount is a fixed amount of the shipping cost")),
        (SHIPPING_FIXED_PRICE, _("Get shipping for a fixed price")),
        (SHIPPING_PERCENTAGE, _("Discount is a percentage off of the shipping"
                                " cost")),
    )
    type = models.CharField(
        _("Type"), max_length=128, choices=TYPE_CHOICES, blank=True)

    # The value to use with the designated type.  This can be either an integer
    # (eg for multibuy) or a decimal (eg an amount) which is slightly
    # confusing.
    # 与指定类型一起使用的值。 这可以是整数（例如，对于multibuy）或小数
    # （例如，数量），这有点令人困惑。
    value = fields.PositiveDecimalField(
        _("Value"), decimal_places=2, max_digits=12, null=True, blank=True)

    # If this is not set, then there is no upper limit on how many products
    # can be discounted by this benefit.
    # 如果未设置，则此优惠可以打折多少产品没有上限。
    max_affected_items = models.PositiveIntegerField(
        _("Max Affected Items"), blank=True, null=True,
        help_text=_("Set this to prevent the discount consuming all items "
                    "within the range that are in the basket."))
    # 设置此选项可防止折扣消耗购物篮中范围内的所有项目。

    # A custom benefit class can be used instead.  This means the
    # type/value/max_affected_items fields should all be None.
    # 可以使用自定义效益类。 这意味着类型/值/ max_affected_items字段都应为None。
    proxy_class = fields.NullCharField(
        _("Custom class"), max_length=255, default=None)

    class Meta:
        abstract = True
        app_label = 'offer'
        verbose_name = _("Benefit")
        verbose_name_plural = _("Benefits")

    @property
    def proxy_map(self):
        return {
            self.PERCENTAGE: get_class(
                'offer.benefits', 'PercentageDiscountBenefit'),
            self.FIXED: get_class(
                'offer.benefits', 'AbsoluteDiscountBenefit'),
            self.MULTIBUY: get_class(
                'offer.benefits', 'MultibuyDiscountBenefit'),
            self.FIXED_PRICE: get_class(
                'offer.benefits', 'FixedPriceBenefit'),
            self.SHIPPING_ABSOLUTE: get_class(
                'offer.benefits', 'ShippingAbsoluteDiscountBenefit'),
            self.SHIPPING_FIXED_PRICE: get_class(
                'offer.benefits', 'ShippingFixedPriceBenefit'),
            self.SHIPPING_PERCENTAGE: get_class(
                'offer.benefits', 'ShippingPercentageDiscountBenefit')
        }

    def apply(self, basket, condition, offer):
        return ZERO_DISCOUNT

    def apply_deferred(self, basket, order, application):
        return None

    def clean(self):
        if not self.type:
            return
        method_name = 'clean_%s' % self.type.lower().replace(' ', '_')
        if hasattr(self, method_name):
            getattr(self, method_name)()

    def clean_multibuy(self):
        errors = []

        if not self.range:
            errors.append(_("Multibuy benefits require a product range"))
        if self.value:
            errors.append(_("Multibuy benefits don't require a value"))
        if self.max_affected_items:
            errors.append(_("Multibuy benefits don't require a "
                            "'max affected items' attribute"))

        if errors:
            raise exceptions.ValidationError(errors)

    def clean_percentage(self):
        errors = []

        if not self.range:
            errors.append(_("Percentage benefits require a product range"))

        if not self.value:
            errors.append(_("Percentage discount benefits require a value"))
        elif self.value > 100:
            errors.append(_("Percentage discount cannot be greater than 100"))

        if errors:
            raise exceptions.ValidationError(errors)

    def clean_shipping_absolute(self):
        errors = []
        if not self.value:
            errors.append(_("A discount value is required"))
        if self.range:
            errors.append(_("No range should be selected as this benefit does "
                            "not apply to products"))
        if self.max_affected_items:
            errors.append(_("Shipping discounts don't require a "
                            "'max affected items' attribute"))

        if errors:
            raise exceptions.ValidationError(errors)

    def clean_shipping_percentage(self):
        errors = []

        if not self.value:
            errors.append(_("Percentage discount benefits require a value"))
        elif self.value > 100:
            errors.append(_("Percentage discount cannot be greater than 100"))

        if self.range:
            errors.append(_("No range should be selected as this benefit does "
                            "not apply to products"))
        if self.max_affected_items:
            errors.append(_("Shipping discounts don't require a "
                            "'max affected items' attribute"))
        if errors:
            raise exceptions.ValidationError(errors)

    def clean_shipping_fixed_price(self):
        errors = []
        if self.range:
            errors.append(_("No range should be selected as this benefit does "
                            "not apply to products"))
        if self.max_affected_items:
            errors.append(_("Shipping discounts don't require a "
                            "'max affected items' attribute"))

        if errors:
            raise exceptions.ValidationError(errors)

    def clean_fixed_price(self):
        if self.range:
            raise exceptions.ValidationError(
                _("No range should be selected as the condition range will "
                  "be used instead."))

    def clean_absolute(self):
        errors = []
        if not self.range:
            errors.append(_("Fixed discount benefits require a product range"))
        if not self.value:
            errors.append(_("Fixed discount benefits require a value"))

        if errors:
            raise exceptions.ValidationError(errors)

    def round(self, amount):
        """
        Apply rounding to discount amount
        适用于折扣金额的四舍五入
        """
        if hasattr(settings, 'OSCAR_OFFER_ROUNDING_FUNCTION'):
            return settings.OSCAR_OFFER_ROUNDING_FUNCTION(amount)
        return amount.quantize(D('.01'), ROUND_DOWN)

    def _effective_max_affected_items(self):
        """
        Return the maximum number of items that can have a discount applied
        during the application of this benefit

        返回在应用此权益期间可以应用折扣的最大项目数
        """
        return self.max_affected_items if self.max_affected_items else 10000

    def can_apply_benefit(self, line):
        """
        Determines whether the benefit can be applied to a given basket line
        确定是否可以将优惠应用于给定的购物篮行
        """
        return line.stockrecord and line.product.is_discountable

    def get_applicable_lines(self, offer, basket, range=None):
        """
        Return the basket lines that are available to be discounted

        :basket: The basket
        :range: The range of products to use for filtering.  The fixed-price
                benefit ignores its range and uses the condition range

         返回可打折的购物篮行
        ：购物篮：购物篮
        ：范围 ：用于过滤的产品范围。 固定价格优惠忽略其范围并使用条件范围
        """
        if range is None:
            range = self.range
        line_tuples = []
        for line in basket.all_lines():
            product = line.product

            if (not range.contains(product) or
                    not self.can_apply_benefit(line)):
                continue

            price = unit_price(offer, line)
            if not price:
                # Avoid zero price products 避免零价格的产品
                continue
            if line.quantity_without_offer_discount(offer) == 0:
                continue
            line_tuples.append((price, line))

        # We sort lines to be cheapest first to ensure consistent applications
        # 我们首先对行进行排序，以确保一致的应用程序
        return sorted(line_tuples, key=operator.itemgetter(0))

    def shipping_discount(self, charge):
        return D('0.00')


# 抽象条件
class AbstractCondition(BaseOfferMixin, models.Model):
    """
    A condition for an offer to be applied. You can either specify a custom
    proxy class, or need to specify a type, range and value.
    要约的条件。 您可以指定自定义代理类，也可以指定类型，范围和值。
    """
    COUNT, VALUE, COVERAGE = ("Count", "Value", "Coverage")
    TYPE_CHOICES = (
        (COUNT, _("Depends on number of items in basket that are in "
                  "condition range")),
        (VALUE, _("Depends on value of items in basket that are in "
                  "condition range")),
        (COVERAGE, _("Needs to contain a set number of DISTINCT items "
                     "from the condition range")))
    range = models.ForeignKey(
        'offer.Range',
        blank=True,
        null=True,
        on_delete=models.CASCADE,
        verbose_name=_("Range"))
    type = models.CharField(_('Type'), max_length=128, choices=TYPE_CHOICES,
                            blank=True)
    value = fields.PositiveDecimalField(
        _('Value'), decimal_places=2, max_digits=12, null=True, blank=True)

    proxy_class = fields.NullCharField(
        _("Custom class"), max_length=255, default=None)

    class Meta:
        abstract = True
        app_label = 'offer'
        verbose_name = _("Condition")
        verbose_name_plural = _("Conditions")

    @property
    def proxy_map(self):
        return {
            self.COUNT: get_class(
                'offer.conditions', 'CountCondition'),
            self.VALUE: get_class(
                'offer.conditions', 'ValueCondition'),
            self.COVERAGE: get_class(
                'offer.conditions', 'CoverageCondition'),
        }

    def consume_items(self, offer, basket, affected_lines):
        pass

    def is_satisfied(self, offer, basket):
        """
        Determines whether a given basket meets this condition.  This is
        stubbed in this top-class object.  The subclassing proxies are
        responsible for implementing it correctly.
        确定给定的篮子是否满足此条件。 这是在这个顶级对象中的存根。 子类代理负责正确实现它。
        """
        return False

    def is_partially_satisfied(self, offer, basket):
        """
        Determine if the basket partially meets the condition.  This is useful
        for up-selling messages to entice customers to buy something more in
        order to qualify for an offer.
        确定购物篮是否部分满足条件。 这对于向上销售消息以吸引客户购买更多东西以获得报价是有用的。
        """
        return False

    def get_upsell_message(self, offer, basket):
        return None

    def can_apply_condition(self, line):
        """
        Determines whether the condition can be applied to a given basket line
        确定条件是否可以应用于给定的购物篮行
        """
        if not line.stockrecord_id:
            return False
        product = line.product
        return (self.range.contains_product(product)
                and product.get_is_discountable())

    def get_applicable_lines(self, offer, basket, most_expensive_first=True):
        """
        Return line data for the lines that can be consumed by this condition
        返回此条件可以使用的行的返回行数据
        """
        line_tuples = []
        for line in basket.all_lines():
            if not self.can_apply_condition(line):
                continue

            price = unit_price(offer, line)
            if not price:
                continue
            line_tuples.append((price, line))
        key = operator.itemgetter(0)
        if most_expensive_first:
            return sorted(line_tuples, reverse=True, key=key)
        return sorted(line_tuples, key=key)


# 抽象范围
class AbstractRange(models.Model):
    """
    Represents a range of products that can be used within an offer.

    Ranges only support adding parent or stand-alone products. Offers will
    consider child products automatically.

    表示可在商品中使用的一系列产品。
    范围仅支持添加父产品或独立产品。 优惠将自动考虑子产品。
    """
    name = models.CharField(_("Name"), max_length=128, unique=True)
    slug = fields.AutoSlugField(
        _("Slug"), max_length=128, unique=True, populate_from="name")

    description = models.TextField(blank=True)

    # Whether this range is public
    # 这个范围是否公开
    is_public = models.BooleanField(
        _('Is public?'), default=False,
        help_text=_("Public ranges have a customer-facing page"))

    includes_all_products = models.BooleanField(
        _('Includes all products?'), default=False)

    included_products = models.ManyToManyField(
        'catalogue.Product', related_name='includes', blank=True,
        verbose_name=_("Included Products"), through='offer.RangeProduct')
    excluded_products = models.ManyToManyField(
        'catalogue.Product', related_name='excludes', blank=True,
        verbose_name=_("Excluded Products"))
    classes = models.ManyToManyField(
        'catalogue.ProductClass', related_name='classes', blank=True,
        verbose_name=_("Product Types"))
    included_categories = models.ManyToManyField(
        'catalogue.Category', related_name='includes', blank=True,
        verbose_name=_("Included Categories"))

    # Allow a custom range instance to be specified
    # 允许指定自定义范围实例
    proxy_class = fields.NullCharField(
        _("Custom class"), max_length=255, default=None, unique=True)

    date_created = models.DateTimeField(_("Date Created"), auto_now_add=True)

    __included_product_ids = None
    __excluded_product_ids = None
    __class_ids = None
    __category_ids = None

    objects = models.Manager()
    browsable = BrowsableRangeManager()

    class Meta:
        abstract = True
        app_label = 'offer'
        verbose_name = _("Range")
        verbose_name_plural = _("Ranges")

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse(
            'catalogue:range', kwargs={'slug': self.slug})

    @cached_property
    def proxy(self):
        if self.proxy_class:
            return load_proxy(self.proxy_class)()

    def add_product(self, product, display_order=None):
        """ Add product to the range

        When adding product that is already in the range, prevent re-adding it.
        If display_order is specified, update it.

        Default display_order for a new product in the range is 0; this puts
        the product at the top of the list.

        将产品添加到该范围

        添加已在范围内的产品时，请阻止重新添加。 如果指定了display_order，请更新它。

        该范围内新产品的默认display_order为0; 这使产品位于列表的顶部。
        """

        initial_order = display_order or 0
        RangeProduct = get_model('offer', 'RangeProduct')
        relation, __ = RangeProduct.objects.get_or_create(
            range=self, product=product,
            defaults={'display_order': initial_order})

        if (display_order is not None and
                relation.display_order != display_order):
            relation.display_order = display_order
            relation.save()

        # Remove product from excluded products if it was removed earlier and
        # re-added again, thus it returns back to the range product list.
        # 如果先前删除了产品并再次重新添加，则从已排除的产品中删除该产品，然后
        # 将其返回到范围产品列表中。
        if product.id in self._excluded_product_ids():
            self.excluded_products.remove(product)
            self.invalidate_cached_ids()

    def remove_product(self, product):
        """
        Remove product from range. To save on queries, this function does not
        check if the product is in fact in the range.
        从范围中移除产品。 为了节省查询，此功能不会检查产品是否实际上在范围内。
        """
        RangeProduct = get_model('offer', 'RangeProduct')
        RangeProduct.objects.filter(range=self, product=product).delete()
        # Making sure product will be excluded from range products list by adding to
        # respective field. Otherwise, it could be included as a product from included
        # category or etc.
        # 通过添加到相应字段，确保将产品从范围产品列表中排除。 否则，它可以作为包含类
        # 别的产品等包含在内。
        self.excluded_products.add(product)
        # Invalidating cached property value with list of IDs of already excluded products.
        # 使用已排除产品的ID列表使缓存的属性值无效。
        self.invalidate_cached_ids()

    def contains_product(self, product):  # noqa (too complex (12))
        """
        Check whether the passed product is part of this range.
        检查通过的产品是否属于此范围。
        """

        # Delegate to a proxy class if one is provided
        # 如果提供了代理类，则委托给代理类
        if self.proxy:
            return self.proxy.contains_product(product)

        excluded_product_ids = self._excluded_product_ids()
        if product.id in excluded_product_ids:
            return False
        if self.includes_all_products:
            return True
        if product.get_product_class().id in self._class_ids():
            return True
        included_product_ids = self._included_product_ids()
        # If the product's parent is in the range, the child is automatically included as well
        # 如果产品的父级在范围内，则子项也会自动包含在内
        if product.is_child and product.parent.id in included_product_ids:
            return True
        if product.id in included_product_ids:
            return True
        test_categories = self.included_categories.all()
        if test_categories:
            for category in product.get_categories().all():
                for test_category in test_categories:
                    if category == test_category \
                            or category.is_descendant_of(test_category):
                        return True
        return False

    # Shorter alias 缩短别名
    contains = contains_product

    def __get_pks_and_child_pks(self, queryset):
        """
        Expects a product queryset; gets the primary keys of the passed
        products and their children.

        Verbose, but database and memory friendly.

        期待产品查询集; 获取传递的产品及其子项的主键。

        详细，但数据库和内存友好。
        """
        # One query to get parent and children; [(4, None), (5, 10), (5, 11)]
        # 获得父级和子产品的一个查询; [（4，无），（5,10），（5,11）]
        pk_tuples_iterable = queryset.values_list('pk', 'children__pk')
        # Flatten list without unpacking; [4, None, 5, 10, 5, 11]
        # 在不拆包的情况下展平列表; [4，无，5,10,5,11]
        flat_iterable = itertools.chain.from_iterable(pk_tuples_iterable)
        # Ensure uniqueness and remove None; {4, 5, 10, 11}
        # 确保唯一性并删除无; {4,5,10,11}
        return set(flat_iterable) - {None}

    def _included_product_ids(self):
        if not self.id:
            return []
        if self.__included_product_ids is None:
            self.__included_product_ids = self.__get_pks_and_child_pks(
                self.included_products)
        return self.__included_product_ids

    def _excluded_product_ids(self):
        if not self.id:
            return []
        if self.__excluded_product_ids is None:
            self.__excluded_product_ids = self.__get_pks_and_child_pks(
                self.excluded_products)
        return self.__excluded_product_ids

    def _class_ids(self):
        if self.__class_ids is None:
            self.__class_ids = self.classes.values_list('pk', flat=True)
        return self.__class_ids

    def _category_ids(self):
        if self.__category_ids is None:
            category_ids_list = list(
                self.included_categories.values_list('pk', flat=True))
            for category in self.included_categories.all():
                children_ids = category.get_descendants().values_list(
                    'pk', flat=True)
                category_ids_list.extend(list(children_ids))

            self.__category_ids = category_ids_list

        return self.__category_ids

    def invalidate_cached_ids(self):
        self.__category_ids = None
        self.__included_product_ids = None
        self.__excluded_product_ids = None

    def num_products(self):
        # Delegate to a proxy class if one is provided
        # 如果提供了代理类，则委托给代理类
        if self.proxy:
            return self.proxy.num_products()
        if self.includes_all_products:
            return None
        return self.all_products().count()

    def all_products(self):
        """
        Return a queryset containing all the products in the range

        This includes included_products plus the products contained in the
        included classes and categories, minus the products in
        excluded_products.

        返回包含范围内所有产品的查询集

        这包括included_products以及包含的类和类别中包含的产品，减去excluded_products中的产品。
        """
        if self.proxy:
            return self.proxy.all_products()

        Product = get_model("catalogue", "Product")
        if self.includes_all_products:
            # Filter out child products
            # 过滤掉子产品
            return Product.browsable.all()

        return Product.objects.filter(
            Q(id__in=self._included_product_ids()) |
            Q(product_class_id__in=self._class_ids()) |
            Q(productcategory__category_id__in=self._category_ids())
        ).exclude(id__in=self._excluded_product_ids()).distinct()

    @property
    def is_editable(self):
        """
        Test whether this range can be edited in the dashboard.
        测试是否可以在仪表板中编辑此范围。
        """
        return not self.proxy_class

    @property
    def is_reorderable(self):
        """
        Test whether products for the range can be re-ordered.
        测试是否可以重新订购该系列的产品。
        """
        return len(self._class_ids()) == 0 and len(self._category_ids()) == 0


# 抽象范围产品
class AbstractRangeProduct(models.Model):
    """
    Allow ordering products inside ranges
    Exists to allow customising.
    允许在范围内订购产品Exists以允许自定义。
    """
    range = models.ForeignKey('offer.Range', on_delete=models.CASCADE)
    product = models.ForeignKey('catalogue.Product', on_delete=models.CASCADE)
    display_order = models.IntegerField(default=0)

    class Meta:
        abstract = True
        app_label = 'offer'
        unique_together = ('range', 'product')


# 抽象范围产品文件上传
class AbstractRangeProductFileUpload(models.Model):
    range = models.ForeignKey(
        'offer.Range',
        on_delete=models.CASCADE,
        related_name='file_uploads',
        verbose_name=_("Range"))
    filepath = models.CharField(_("File Path"), max_length=255)
    size = models.PositiveIntegerField(_("Size"))
    uploaded_by = models.ForeignKey(
        AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        verbose_name=_("Uploaded By"))
    date_uploaded = models.DateTimeField(_("Date Uploaded"), auto_now_add=True)

    PENDING, FAILED, PROCESSED = 'Pending', 'Failed', 'Processed'
    choices = (
        (PENDING, PENDING),
        (FAILED, FAILED),
        (PROCESSED, PROCESSED),
    )
    status = models.CharField(_("Status"), max_length=32, choices=choices,
                              default=PENDING)
    error_message = models.CharField(_("Error Message"), max_length=255,
                                     blank=True)

    # Post-processing audit fields
    # 后处理审计字段
    date_processed = models.DateTimeField(_("Date Processed"), null=True)
    num_new_skus = models.PositiveIntegerField(_("Number of New SKUs"),
                                               null=True)
    num_unknown_skus = models.PositiveIntegerField(_("Number of Unknown SKUs"),
                                                   null=True)
    num_duplicate_skus = models.PositiveIntegerField(
        _("Number of Duplicate SKUs"), null=True)

    class Meta:
        abstract = True
        app_label = 'offer'
        ordering = ('-date_uploaded',)
        verbose_name = _("Range Product Uploaded File")
        verbose_name_plural = _("Range Product Uploaded Files")

    @property
    def filename(self):
        return os.path.basename(self.filepath)

    def mark_as_failed(self, message=None):
        self.date_processed = now()
        self.error_message = message
        self.status = self.FAILED
        self.save()

    def mark_as_processed(self, num_new, num_unknown, num_duplicate):
        self.status = self.PROCESSED
        self.date_processed = now()
        self.num_new_skus = num_new
        self.num_unknown_skus = num_unknown
        self.num_duplicate_skus = num_duplicate
        self.save()

    def was_processing_successful(self):
        return self.status == self.PROCESSED

    def process(self):
        """
        Process the file upload and add products to the range
        处理文件上载并将产品添加到范围
        """
        all_ids = set(self.extract_ids())
        products = self.range.all_products()
        existing_skus = products.values_list(
            'stockrecords__partner_sku', flat=True)
        existing_skus = set(filter(bool, existing_skus))
        existing_upcs = products.values_list('upc', flat=True)
        existing_upcs = set(filter(bool, existing_upcs))
        existing_ids = existing_skus.union(existing_upcs)
        new_ids = all_ids - existing_ids

        Product = get_model('catalogue', 'Product')
        products = Product._default_manager.filter(
            models.Q(stockrecords__partner_sku__in=new_ids) |
            models.Q(upc__in=new_ids))
        for product in products:
            self.range.add_product(product)

        # Processing stats 处理统计数据
        found_skus = products.values_list(
            'stockrecords__partner_sku', flat=True)
        found_skus = set(filter(bool, found_skus))
        found_upcs = set(filter(bool, products.values_list('upc', flat=True)))
        found_ids = found_skus.union(found_upcs)
        missing_ids = new_ids - found_ids
        dupes = set(all_ids).intersection(existing_ids)

        self.mark_as_processed(products.count(), len(missing_ids), len(dupes))
        return products

    def extract_ids(self):
        """
        Extract all SKU- or UPC-like strings from the file
        从文件中提取所有类似SKU或UPC的字符串
        """
        with open(self.filepath, 'r') as fh:
            for line in fh:
                for id in re.split('[^\w:\.-]', line):
                    if id:
                        yield id

    def delete_file(self):
        os.unlink(self.filepath)
