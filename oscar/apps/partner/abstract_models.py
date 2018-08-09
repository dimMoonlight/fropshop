from django.db import models, router
from django.db.models import F, Value, signals
from django.db.models.functions import Coalesce
from django.utils.functional import cached_property
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _
from django.utils.translation import pgettext_lazy

from oscar.apps.partner.exceptions import InvalidStockAdjustment
from oscar.core.compat import AUTH_USER_MODEL
from oscar.core.utils import get_default_currency
from oscar.models.fields import AutoSlugField


class AbstractPartner(models.Model):
    """
    A fulfillment partner. An individual or company who can fulfil products.
    E.g. for physical goods, somebody with a warehouse and means of delivery.

    Creating one or more instances of the Partner model is a required step in
    setting up an Oscar deployment. Many Oscar deployments will only have one
    fulfillment partner.

    履行合作伙伴。 可以履行产品的个人或公司。
    例如。 对于实物商品，有仓库和交货方式的人。

    创建合作伙伴模型的一个或多个实例是设置Oscar部署的必要步骤。 许多奥斯卡
    部署只会有一个履行合作伙伴。
    """
    code = AutoSlugField(_("Code"), max_length=128, unique=True,
                         populate_from='name')
    name = models.CharField(
        pgettext_lazy("Partner's name", "Name"), max_length=128, blank=True)

    #: A partner can have users assigned to it. This is used
    #: for access modelling in the permission-based dashboard
    # 合作伙伴可以为其分配用户。 这用于基于权限的仪表板中的访问建模
    users = models.ManyToManyField(
        AUTH_USER_MODEL, related_name="partners",
        blank=True, verbose_name=_("Users"))

    @property
    def display_name(self):
        return self.name or self.code

    @property
    def primary_address(self):
        """
        Returns a partners primary address. Usually that will be the
        headquarters or similar.

        This is a rudimentary implementation that raises an error if there's
        more than one address. If you actually want to support multiple
        addresses, you will likely need to extend PartnerAddress to have some
        field or flag to base your decision on.

        返回合作伙伴主要地址。 通常那将是总部或类似的。
        这是一个基本实现，如果有多个地址，则会引发错误。 如果您确实希望支持
        多个地址，则可能需要扩展PartnerAddress以使某些字段或标记作为您的决策依据。
        """
        addresses = self.addresses.all()
        if len(addresses) == 0:  # intentionally using len() to save queries 故意使用len（）来保存查询
            return None
        elif len(addresses) == 1:
            return addresses[0]
        else:
            raise NotImplementedError(
                "Oscar's default implementation of primary_address only "
                "supports one PartnerAddress.  You need to override the "
                "primary_address to look up the right address")

    def get_address_for_stockrecord(self, stockrecord):
        """
        Stock might be coming from different warehouses. Overriding this
        function allows selecting the correct PartnerAddress for the record.
        That can be useful when determining tax.
        库存可能来自不同的仓库。 覆盖此功能允许为记录选择正确的PartnerAddress。
        这在确定税时很有用。
        """
        return self.primary_address

    class Meta:
        abstract = True
        app_label = 'partner'
        ordering = ('name', 'code')
        permissions = (('dashboard_access', 'Can access dashboard'), )
        verbose_name = _('Fulfillment partner')
        verbose_name_plural = _('Fulfillment partners')

    def __str__(self):
        return self.display_name


class AbstractStockRecord(models.Model):
    """
    A stock record.

    This records information about a product from a fulfilment partner, such as
    their SKU, the number they have in stock and price information.

    Stockrecords are used by 'strategies' to determine availability and pricing
    information for the customer.

    库存记录。
    这会记录有关履行合作伙伴的产品的信息，例如其SKU，库存中的数量和价格信息。
    “策略”使用库存记录来确定客户的可用性和定价信息。
    """
    product = models.ForeignKey(
        'catalogue.Product',
        on_delete=models.CASCADE,
        related_name="stockrecords",
        verbose_name=_("Product"))
    partner = models.ForeignKey(
        'partner.Partner',
        on_delete=models.CASCADE,
        verbose_name=_("Partner"),
        related_name='stockrecords')

    #: The fulfilment partner will often have their own SKU for a product,
    #: which we store here.  This will sometimes be the same the product's UPC
    #: but not always.  It should be unique per partner.
    #: See also http://en.wikipedia.org/wiki/Stock-keeping_unit
    # 履行合作伙伴通常会为我们存储的产品拥有自己的SKU。 这有时与产品的UPC相同，但
    # 并非总是如此。 每个合作伙伴应该是唯一的。SKU（最小库存单位）UPC（ 通用产品代码）
    # 参见http://en.wikipedia.org/wiki/Stock-keeping_unit
    partner_sku = models.CharField(_("Partner SKU"), max_length=128)

    # Price info: 价格信息：
    price_currency = models.CharField(
        _("Currency"), max_length=12, default=get_default_currency)

    # This is the base price for calculations - tax should be applied by the
    # appropriate method.  We don't store tax here as its calculation is highly
    # domain-specific.  It is NULLable because some items don't have a fixed
    # price but require a runtime calculation (possible from an external
    # service). Current field name `price_excl_tax` is deprecated and will be
    # renamed into `price` in Oscar 2.0.
    # 这是计算的基本价格-应该采用适当的方法征税。我们不在这里存储税，因为它的计算
    # 是高度特定于域的。它是可空的，因为有些项目没有固定的价格，但需要运行时计算
    # （可能来自外部服务）。当前字段名“Price OxExcLoCuffy”已被弃用，将在
    # 奥斯卡2中重命名为“价格”。
    price_excl_tax = models.DecimalField(
        _("Price (excl. tax)"), decimal_places=2, max_digits=12,
        blank=True, null=True)

    # Deprecated - will be removed in Oscar 2.0
    # 已弃用 - 将在Oscar 2.0中删除
    price_retail = models.DecimalField(
        _("Price (retail)"), decimal_places=2, max_digits=12,
        blank=True, null=True)

    # Deprecated - will be removed in Oscar 2.0
    # 已弃用 - 将在Oscar 2.0中删除
    cost_price = models.DecimalField(
        _("Cost Price"), decimal_places=2, max_digits=12,
        blank=True, null=True)

    #: Number of items in stock
    # 库存商品数量
    num_in_stock = models.PositiveIntegerField(
        _("Number in stock"), blank=True, null=True)

    #: The amount of stock allocated to orders but not fed back to the master
    #: stock system.  A typical stock update process will set the num_in_stock
    #: variable to a new value and reset num_allocated to zero
    # 分配给订单但未反馈给主库存系统的库存量。 典型的库存更新过程会将num_in_stock变
    # 量设置为新值，并将num_allocated重置为零
    num_allocated = models.IntegerField(
        _("Number allocated"), blank=True, null=True)

    #: Threshold for low-stock alerts.  When stock goes beneath this threshold,
    #: an alert is triggered so warehouse managers can order more.
    # 低库存警报的阈值。 当库存低于此阈值时，将触发警报，以便仓库经理可以订购更多。
    low_stock_threshold = models.PositiveIntegerField(
        _("Low Stock Threshold"), blank=True, null=True)

    # Date information 日期信息
    date_created = models.DateTimeField(_("Date created"), auto_now_add=True)
    date_updated = models.DateTimeField(_("Date updated"), auto_now=True,
                                        db_index=True)

    def __str__(self):
        msg = "Partner: %s, product: %s" % (
            self.partner.display_name, self.product,)
        if self.partner_sku:
            msg = "%s (%s)" % (msg, self.partner_sku)
        return msg

    class Meta:
        abstract = True
        app_label = 'partner'
        unique_together = ('partner', 'partner_sku')
        verbose_name = _("Stock record")
        verbose_name_plural = _("Stock records")

    @property
    def net_stock_level(self):
        """
        The effective number in stock (eg available to buy).

        This is correct property to show the customer, not the num_in_stock
        field as that doesn't account for allocations.  This can be negative in
        some unusual circumstances

        库存中的有效数量（例如可供购买）。
        这是显示客户的正确属性，而不是num_in_stock字段，因为它不考虑分配。 在某
        些特殊情况下，这可能是负面的
        """
        if self.num_in_stock is None:
            return 0
        if self.num_allocated is None:
            return self.num_in_stock
        return self.num_in_stock - self.num_allocated

    @cached_property
    def can_track_allocations(self):
        """
        Return True if the Product is set for stock tracking.
        如果将产品设置为库存跟踪，则返回True。
        """
        return self.product.get_product_class().track_stock

    # 2-stage stock management model
    # 两阶段库存管理模型
    def allocate(self, quantity):
        """
        Record a stock allocation.

        This normally happens when a product is bought at checkout.  When the
        product is actually shipped, then we 'consume' the allocation.

        记录库存分配。
        这通常发生在结账时购买产品。 当产品实际发货时，我们“消耗”分配。
        """
        # Doesn't make sense to allocate if stock tracking is off.
        # 如果库存跟踪关闭则分配没有意义。
        if not self.can_track_allocations:
            return
        # Send the pre-save signal
        # 发送预保存信号
        signals.pre_save.send(
            sender=self.__class__,
            instance=self,
            created=False,
            raw=False,
            using=router.db_for_write(self.__class__, instance=self))

        # Atomic update 原子更新
        (self.__class__.objects
            .filter(pk=self.pk)
            .update(num_allocated=(
                Coalesce(F('num_allocated'), Value(0)) + quantity)))

        # Make sure the current object is up-to-date
        # 确保当前对象是最新的
        if self.num_allocated is None:
            self.num_allocated = 0
        self.num_allocated += quantity

        # Send the post-save signal
        # 发送保存后信号
        signals.post_save.send(
            sender=self.__class__,
            instance=self,
            created=False,
            raw=False,
            using=router.db_for_write(self.__class__, instance=self))

    allocate.alters_data = True

    def is_allocation_consumption_possible(self, quantity):
        """
        Test if a proposed stock consumption is permitted
        测试是否允许建议的库存消耗
        """
        return quantity <= min(self.num_allocated, self.num_in_stock)

    def consume_allocation(self, quantity):
        """
        Consume a previous allocation

        This is used when an item is shipped.  We remove the original
        allocation and adjust the number in stock accordingly

        消耗先前的分配
        这是在物品发货时使用的。 我们删除原始分配并相应调整库存数量
        """
        if not self.can_track_allocations:
            return
        if not self.is_allocation_consumption_possible(quantity):
            raise InvalidStockAdjustment(
                _('Invalid stock consumption request'))
        self.num_allocated -= quantity
        self.num_in_stock -= quantity
        self.save()
    consume_allocation.alters_data = True

    def cancel_allocation(self, quantity):
        if not self.can_track_allocations:
            return
        # We ignore requests that request a cancellation of more than the
        # amount already allocated.
        # 我们忽略请求取消超过已分配金额的请求。
        self.num_allocated -= min(self.num_allocated, quantity)
        self.save()
    cancel_allocation.alters_data = True

    @property
    def is_below_threshold(self):
        if self.low_stock_threshold is None:
            return False
        return self.net_stock_level < self.low_stock_threshold


class AbstractStockAlert(models.Model):
    """
    A stock alert. E.g. used to notify users when a product is 'back in stock'.
    库存警报。 例如。 用于在产品“重新库存”时通知用户。
    """
    stockrecord = models.ForeignKey(
        'partner.StockRecord',
        on_delete=models.CASCADE,
        related_name='alerts',
        verbose_name=_("Stock Record"))
    threshold = models.PositiveIntegerField(_("Threshold"))
    OPEN, CLOSED = "Open", "Closed"
    status_choices = (
        (OPEN, _("Open")),
        (CLOSED, _("Closed")),
    )
    status = models.CharField(_("Status"), max_length=128, default=OPEN,
                              choices=status_choices)
    date_created = models.DateTimeField(_("Date Created"), auto_now_add=True)
    date_closed = models.DateTimeField(_("Date Closed"), blank=True, null=True)

    def close(self):
        self.status = self.CLOSED
        self.date_closed = now()
        self.save()
    close.alters_data = True

    def __str__(self):
        return _('<stockalert for "%(stock)s" status %(status)s>') \
            % {'stock': self.stockrecord, 'status': self.status}

    class Meta:
        abstract = True
        app_label = 'partner'
        ordering = ('-date_created',)
        verbose_name = _('Stock alert')
        verbose_name_plural = _('Stock alerts')
