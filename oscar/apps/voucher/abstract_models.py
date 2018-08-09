from decimal import Decimal

from django.core import exceptions
from django.db import models, transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from oscar.apps.voucher.utils import get_unused_code
from oscar.core.compat import AUTH_USER_MODEL
from oscar.core.loading import get_model


class AbstractVoucherSet(models.Model):
    """A collection of vouchers (potentially auto-generated)

    a VoucherSet is a group of voucher that are generated
    automatically.

    - count: the minimum number of vouchers in the set. If this is kept at
    zero, vouchers are created when and as needed.

    - code_length: the length of the voucher code. Codes are by default created
    with groups of 4 characters: XXXX-XXXX-XXXX. The dashes (-) do not count for
    the code_length.

    - start_datetime, end_datetime: defines the validity datetime range for
    all vouchers in the set.

    凭证集合（可能是自动生成的）
    VoucherSet是一组自动生成的凭证。
    - count：集合中的最小凭证数。 如果保持为零，则会根据需要创建凭证。
    - code_length：凭证代码的长度。 默认情况下，代码是使用4个字符的组创建
                    的：XXXX-XXXX-XXXX。 短划线（ - ）不计入code_length。
    - start_datetime，end_datetime：定义集合中所有凭证的有效日期时间范围。
    """

    name = models.CharField(verbose_name=_('Name'), max_length=100)
    count = models.PositiveIntegerField(verbose_name=_('Number of vouchers'))
    code_length = models.IntegerField(
        verbose_name=_('Length of Code'), default=12)
    description = models.TextField(verbose_name=_('Description'))
    date_created = models.DateTimeField(auto_now_add=True)
    start_datetime = models.DateTimeField(_('Start datetime'))
    end_datetime = models.DateTimeField(_('End datetime'))

    offer = models.OneToOneField(
        'offer.ConditionalOffer', related_name='voucher_set',
        verbose_name=_("Offer"), limit_choices_to={'offer_type': "Voucher"},
        on_delete=models.CASCADE, null=True, blank=True)

    class Meta:
        abstract = True
        app_label = 'voucher'
        get_latest_by = 'date_created'
        verbose_name = _("VoucherSet")
        verbose_name_plural = _("VoucherSets")

    def __str__(self):
        return self.name

    def generate_vouchers(self):
        """
        Generate vouchers for this set
        为此套件生成优惠券
        """
        current_count = self.vouchers.count()
        for i in range(current_count, self.count):
            self.add_new()

    def add_new(self):
        """
        Add a new voucher to this set
        在此套装中添加新凭证
        """
        Voucher = get_model('voucher', 'Voucher')
        code = get_unused_code(length=self.code_length)
        voucher = Voucher.objects.create(
            name=self.name,
            code=code,
            voucher_set=self,
            usage=Voucher.SINGLE_USE,
            start_datetime=self.start_datetime,
            end_datetime=self.end_datetime)

        if self.offer:
            voucher.offers.add(self.offer)

        return voucher

    def is_active(self, test_datetime=None):
        """
        Test whether this voucher set is currently active.
        测试此凭证集当前是否处于活动状态。
         """
        test_datetime = test_datetime or timezone.now()
        return self.start_datetime <= test_datetime <= self.end_datetime

    def save(self, *args, **kwargs):
        self.count = max(self.count, self.vouchers.count())
        with transaction.atomic():
            super().save(*args, **kwargs)
            self.generate_vouchers()
            self.vouchers.update(
                start_datetime=self.start_datetime,
                end_datetime=self.end_datetime
            )

    @property
    def num_basket_additions(self):
        value = self.vouchers.aggregate(result=Sum('num_basket_additions'))
        return value['result']

    @property
    def num_orders(self):
        value = self.vouchers.aggregate(result=Sum('num_orders'))
        return value['result']

    @property
    def total_discount(self):
        value = self.vouchers.aggregate(result=Sum('total_discount'))
        return value['result']


class AbstractVoucher(models.Model):
    """
    A voucher.  This is simply a link to a collection of offers.

    Note that there are three possible "usage" modes:
    (a) Single use
    (b) Multi-use
    (c) Once per customer

    Oscar enforces those modes by creating VoucherApplication
    instances when a voucher is used for an order.

    凭证。 这只是一系列优惠的链接。
    请注意，有三种可能的“使用”模式：
    （a）单次使用
    （b）多用途
    （c）每位顾客一次
    当凭证用于订单时，Oscar通过创建VoucherApplication实例来强制执行这些模式。
    """
    name = models.CharField(_("Name"), max_length=128,
                            help_text=_("This will be shown in the checkout"
                                        " and basket once the voucher is"
                                        " entered"))
    code = models.CharField(_("Code"), max_length=128, db_index=True,
                            unique=True, help_text=_("Case insensitive / No"
                                                     " spaces allowed"))
    offers = models.ManyToManyField(
        'offer.ConditionalOffer', related_name='vouchers',
        verbose_name=_("Offers"), limit_choices_to={'offer_type': "Voucher"})

    SINGLE_USE, MULTI_USE, ONCE_PER_CUSTOMER = (
        'Single use', 'Multi-use', 'Once per customer')
    USAGE_CHOICES = (
        (SINGLE_USE, _("Can be used once by one customer")),
        (MULTI_USE, _("Can be used multiple times by multiple customers")),
        (ONCE_PER_CUSTOMER, _("Can only be used once per customer")),
    )
    usage = models.CharField(_("Usage"), max_length=128,
                             choices=USAGE_CHOICES, default=MULTI_USE)

    start_datetime = models.DateTimeField(_('Start datetime'))
    end_datetime = models.DateTimeField(_('End datetime'))

    # Reporting information. Not used to enforce any consumption limits.
    # 报告信息。 不习惯强制执行任何消费限制。
    num_basket_additions = models.PositiveIntegerField(
        _("Times added to basket"), default=0)
    num_orders = models.PositiveIntegerField(_("Times on orders"), default=0)
    total_discount = models.DecimalField(
        _("Total discount"), decimal_places=2, max_digits=12,
        default=Decimal('0.00'))

    voucher_set = models.ForeignKey(
        'voucher.VoucherSet', null=True, blank=True, related_name='vouchers',
        on_delete=models.CASCADE
    )

    date_created = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        app_label = 'voucher'
        get_latest_by = 'date_created'
        verbose_name = _("Voucher")
        verbose_name_plural = _("Vouchers")

    def __str__(self):
        return self.name

    def clean(self):
        if all([self.start_datetime, self.end_datetime,
                self.start_datetime > self.end_datetime]):
            raise exceptions.ValidationError(
                _('End date should be later than start date'))

    def save(self, *args, **kwargs):
        self.code = self.code.upper()
        super().save(*args, **kwargs)

    def is_active(self, test_datetime=None):
        """
        Test whether this voucher is currently active.
        测试此凭证当前是否有效。
        """
        test_datetime = test_datetime or timezone.now()
        return self.start_datetime <= test_datetime <= self.end_datetime

    def is_expired(self):
        """
        Test whether this voucher has passed its expiration date
        测试此凭证是否已超过其到期日期
        """
        now = timezone.now()
        return self.end_datetime < now

    def is_available_to_user(self, user=None):
        """
        Test whether this voucher is available to the passed user.

        Returns a tuple of a boolean for whether it is successful, and a
        availability message.

        测试此凭证是否可供传递的用户使用。
        返回布尔值的元组，表示它是否成功，以及可用性消息。
        """
        is_available, message = False, ''
        if self.usage == self.SINGLE_USE:
            is_available = not self.applications.exists()
            if not is_available:
                message = _("This voucher has already been used")
        elif self.usage == self.MULTI_USE:
            is_available = True
        elif self.usage == self.ONCE_PER_CUSTOMER:
            if not user.is_authenticated:
                is_available = False
                message = _(
                    "This voucher is only available to signed in users")
            else:
                is_available = not self.applications.filter(
                    voucher=self, user=user).exists()
                if not is_available:
                    message = _("You have already used this voucher in "
                                "a previous order")
        return is_available, message

    def record_usage(self, order, user):
        """
        Records a usage of this voucher in an order.
        在订单中记录此凭证的使用情况。
        """
        if user.is_authenticated:
            self.applications.create(voucher=self, order=order, user=user)
        else:
            self.applications.create(voucher=self, order=order)
        self.num_orders += 1
        self.save()
    record_usage.alters_data = True

    def record_discount(self, discount):
        """
        Record a discount that this offer has given
        记录此优惠给出的折扣
        """
        self.total_discount += discount['discount']
        self.save()
    record_discount.alters_data = True

    @property
    def benefit(self):
        """
        Returns the first offer's benefit instance.

        A voucher is commonly only linked to one offer. In that case,
        this helper can be used for convenience.

        返回第一个商品的福利实例。
        优惠券通常仅与一个优惠相关联。 在这种情况下，可以使用该帮助器以方便使用。
        """
        return self.offers.all()[0].benefit


class AbstractVoucherApplication(models.Model):
    """
    For tracking how often a voucher has been used in an order.

    This is used to enforce the voucher usage mode in
    Voucher.is_available_to_user, and created in Voucher.record_usage.

    用于跟踪凭证在订单中的使用频率。
    这用于在Voucher.is_available_to_user中强制执行凭证使用模式，
    并在Voucher.record_usage中创建。
    """
    voucher = models.ForeignKey(
        'voucher.Voucher',
        on_delete=models.CASCADE,
        related_name="applications",
        verbose_name=_("Voucher"))

    # It is possible for an anonymous user to apply a voucher so we need to
    # allow the user to be nullable
    # 匿名用户可以应用凭证，因此我们需要允许用户可以为空
    user = models.ForeignKey(
        AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.CASCADE,
        verbose_name=_("User"))
    order = models.ForeignKey(
        'order.Order',
        on_delete=models.CASCADE,
        verbose_name=_("Order"))
    date_created = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        app_label = 'voucher'
        verbose_name = _("Voucher Application")
        verbose_name_plural = _("Voucher Applications")

    def __str__(self):
        return _("'%(voucher)s' used by '%(user)s'") % {
            'voucher': self.voucher,
            'user': self.user}
