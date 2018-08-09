import hashlib
import logging
from collections import OrderedDict
from decimal import Decimal as D

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.signing import BadSignature, Signer
from django.db import models
from django.db.models import Sum
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _
from django.utils.translation import pgettext_lazy

from oscar.apps.order.signals import (
    order_line_status_changed, order_status_changed)
from oscar.core.compat import AUTH_USER_MODEL
from oscar.core.loading import get_model
from oscar.core.utils import get_default_currency
from oscar.models.fields import AutoSlugField

from . import exceptions


logger = logging.getLogger('oscar.order')


# 抽象订单
class AbstractOrder(models.Model):
    """
    The main order model 主要订单模型
    """
    number = models.CharField(
        _("Order number"), max_length=128, db_index=True, unique=True)

    # We track the site that each order is placed within
    # 我们跟踪每个订单所在的网站
    site = models.ForeignKey(
        'sites.Site', verbose_name=_("Site"), null=True,
        on_delete=models.SET_NULL)

    basket = models.ForeignKey(
        'basket.Basket', verbose_name=_("Basket"),
        null=True, blank=True, on_delete=models.SET_NULL)

    # Orders can be placed without the user authenticating so we don't always
    # have a customer ID.
    # 订单可以在没有用户身份验证的情况下放置，因此我们并不总是拥有客户ID。
    user = models.ForeignKey(
        AUTH_USER_MODEL, related_name='orders', null=True, blank=True,
        verbose_name=_("User"), on_delete=models.SET_NULL)

    # Billing address is not always required (eg paying by gift card)
    # 不一定需要结算地址（例如通过礼品卡付款）
    billing_address = models.ForeignKey(
        'order.BillingAddress', null=True, blank=True,
        verbose_name=_("Billing Address"),
        on_delete=models.SET_NULL)

    # Total price looks like it could be calculated by adding up the
    # prices of the associated lines, but in some circumstances extra
    # order-level charges are added and so we need to store it separately
    # 总价看起来可以通过将相关行的价格相加来计算，但在某些情况下会增加额外
    # 的订单级费用，因此我们需要单独存储它
    currency = models.CharField(
        _("Currency"), max_length=12, default=get_default_currency)
    total_incl_tax = models.DecimalField(
        _("Order total (inc. tax)"), decimal_places=2, max_digits=12)
    total_excl_tax = models.DecimalField(
        _("Order total (excl. tax)"), decimal_places=2, max_digits=12)

    # Shipping charges 运费
    shipping_incl_tax = models.DecimalField(
        _("Shipping charge (inc. tax)"), decimal_places=2, max_digits=12,
        default=0)
    shipping_excl_tax = models.DecimalField(
        _("Shipping charge (excl. tax)"), decimal_places=2, max_digits=12,
        default=0)

    # Not all lines are actually shipped (such as downloads), hence shipping
    # address is not mandatory.
    # 并非所有线路都已发货（例如下载），因此送货地址不是强制性的。
    shipping_address = models.ForeignKey(
        'order.ShippingAddress', null=True, blank=True,
        verbose_name=_("Shipping Address"),
        on_delete=models.SET_NULL)
    shipping_method = models.CharField(
        _("Shipping method"), max_length=128, blank=True)

    # Identifies shipping code
    # 标识运输代码
    shipping_code = models.CharField(blank=True, max_length=128, default="")

    # Use this field to indicate that an order is on hold / awaiting payment
    # 使用此字段表示订单处于暂停/等待付款
    status = models.CharField(_("Status"), max_length=100, blank=True)
    guest_email = models.EmailField(_("Guest email address"), blank=True)

    # Index added to this field for reporting
    # 索引已添加到此字段以进行报告
    date_placed = models.DateTimeField(db_index=True)

    #: Order status pipeline.  This should be a dict where each (key, value) #:
    #: corresponds to a status and a list of possible statuses that can follow
    #: that one.
    # 订单状态管道。 这应该是一个dict，其中每个（键，值）＃：对应一个状态和
    # 一个可以遵循该状态的可能状态列表。
    pipeline = getattr(settings, 'OSCAR_ORDER_STATUS_PIPELINE', {})

    #: Order status cascade pipeline.  This should be a dict where each (key,
    #: value) pair corresponds to an *order* status and the corresponding
    #: *line* status that needs to be set when the order is set to the new
    #: status
    # 订单状态级联管道。 这应该是一个dict，其中每个（键，值）对对应
    # 于* order * status以及当订单设置为新状态时需要设置的相应* line *状态
    cascade = getattr(settings, 'OSCAR_ORDER_STATUS_CASCADE', {})

    @classmethod
    def all_statuses(cls):
        """
        Return all possible statuses for an order
        返回订单的所有可能状态
        """
        return list(cls.pipeline.keys())

    def available_statuses(self):
        """
        Return all possible statuses that this order can move to
        返回此订单可以移动到的所有可能状态
        """
        return self.pipeline.get(self.status, ())

    def set_status(self, new_status):
        """
        Set a new status for this order.

        If the requested status is not valid, then ``InvalidOrderStatus`` is
        raised.
        为此订单设置新状态。
        如果请求的状态无效，则引发“InvalidOrderStatus”(订单状态无效)。
        """
        if new_status == self.status:
            return

        old_status = self.status

        if new_status not in self.available_statuses():
            raise exceptions.InvalidOrderStatus(
                _("'%(new_status)s' is not a valid status for order %(number)s"
                  " (current status: '%(status)s')")
                % {'new_status': new_status,
                   'number': self.number,
                   'status': self.status})
        self.status = new_status
        if new_status in self.cascade:
            for line in self.lines.all():
                line.status = self.cascade[self.status]
                line.save()
        self.save()

        # Send signal for handling status changed
        # 处理状态的发送信号已更改
        order_status_changed.send(sender=self,
                                  order=self,
                                  old_status=old_status,
                                  new_status=new_status,
                                  )

    set_status.alters_data = True

    @property
    def is_anonymous(self):
        # It's possible for an order to be placed by a customer who then
        # deletes their profile.  Hence, we need to check that a guest email is
        # set.
        # 客户可以下订单然后删除他们的个人资料。 因此，我们需要检查是否设置了访客电子邮件。
        return self.user is None and bool(self.guest_email)

    @property
    def basket_total_before_discounts_incl_tax(self):
        """
        Return basket total including tax but before discounts are applied
        返回 购物篮总额，包括税，但在折扣前应用
        """
        total = D('0.00')
        for line in self.lines.all():
            total += line.line_price_before_discounts_incl_tax
        return total

    @property
    def basket_total_before_discounts_excl_tax(self):
        """
        Return basket total excluding tax but before discounts are applied
        返回 购物篮总额不含税但折扣前应用
        """
        total = D('0.00')
        for line in self.lines.all():
            total += line.line_price_before_discounts_excl_tax
        return total

    @property
    def basket_total_incl_tax(self):
        """
        Return basket total including tax
        返回购物篮总额包括税
        """
        return self.total_incl_tax - self.shipping_incl_tax

    @property
    def basket_total_excl_tax(self):
        """
        Return basket total excluding tax
        返回购物篮总额不包括税
        """
        return self.total_excl_tax - self.shipping_excl_tax

    @property
    def total_before_discounts_incl_tax(self):
        return (self.basket_total_before_discounts_incl_tax +
                self.shipping_incl_tax)

    @property
    def total_before_discounts_excl_tax(self):
        return (self.basket_total_before_discounts_excl_tax +
                self.shipping_excl_tax)

    @property
    def total_discount_incl_tax(self):
        """
        The amount of discount this order received
        此订单收到的折扣金额
        """
        discount = D('0.00')
        for line in self.lines.all():
            discount += line.discount_incl_tax
        return discount

    @property
    def total_discount_excl_tax(self):
        discount = D('0.00')
        for line in self.lines.all():
            discount += line.discount_excl_tax
        return discount

    @property
    def total_tax(self):
        return self.total_incl_tax - self.total_excl_tax

    @property
    def num_lines(self):
        return self.lines.count()

    @property
    def num_items(self):
        """
        Returns the number of items in this order.
        按此顺序返回项目的数量。
        """
        num_items = 0
        for line in self.lines.all():
            num_items += line.quantity
        return num_items

    @property
    def shipping_tax(self):
        return self.shipping_incl_tax - self.shipping_excl_tax

    @property
    def shipping_status(self):
        """
        Return the last complete shipping event for this order.
        返回此订单的最后一次完整的运输事件。
        """

        # As safeguard against identical timestamps, also sort by the primary
        # key. It's not recommended to rely on this behaviour, but in practice
        # reasonably safe if PKs are not manually set.
        # 作为防止相同时间戳的安全措施，还要按主键排序。 不建议依赖此行为，但
        # 实际上如果不手动设置PK则相当安全。
        events = self.shipping_events.order_by('-date_created', '-pk').all()
        if not len(events):
            return ''

        # Collect all events by event-type
        # 按事件类型收集所有事件
        event_map = OrderedDict()
        for event in events:
            event_name = event.event_type.name
            if event_name not in event_map:
                event_map[event_name] = []
            event_map[event_name].extend(list(event.line_quantities.all()))

        # Determine last complete event
        # 确定上次完成的事件
        status = _("In progress")
        for event_name, event_line_quantities in event_map.items():
            if self._is_event_complete(event_line_quantities):
                return event_name
        return status

    @property
    def has_shipping_discounts(self):
        return len(self.shipping_discounts) > 0

    @property
    def shipping_before_discounts_incl_tax(self):
        # We can construct what shipping would have been before discounts by
        # adding the discounts back onto the final shipping charge.
        # 我们可以通过将折扣添加回最终运费来构建折扣前的运费。
        total = D('0.00')
        for discount in self.shipping_discounts:
            total += discount.amount
        return self.shipping_incl_tax + total

    def _is_event_complete(self, event_quantities):
        # Form map of line to quantity
        # 形成线到数量的地图
        event_map = {}
        for event_quantity in event_quantities:
            line_id = event_quantity.line_id
            event_map.setdefault(line_id, 0)
            event_map[line_id] += event_quantity.quantity

        for line in self.lines.all():
            if event_map.get(line.pk, 0) != line.quantity:
                return False
        return True

    class Meta:
        abstract = True
        app_label = 'order'
        ordering = ['-date_placed']
        verbose_name = _("Order")
        verbose_name_plural = _("Orders")

    def __str__(self):
        return "#%s" % (self.number,)

    def verification_hash(self):
        signer = Signer(salt='oscar.apps.order.Order')
        return signer.sign(self.number)

    def check_deprecated_verification_hash(self, hash_to_check):
        """
        Backward compatible check for md5 hashes that were generated in
        Oscar 1.5 and lower.

        This must explicitly be enabled by setting OSCAR_DEPRECATED_ORDER_VERIFY_KEY,
        which must not be equal to SECRET_KEY - i.e., the project must
        have changed its SECRET_KEY since this change was applied.

        TODO: deprecate this method in Oscar 2.0, and remove it in Oscar 2.1.

        向后兼容检查在Oscar 1.5及更低版本中生成的md5哈希值。

        必须通过设置OSCAR_DEPRECATED_ORDER_VERIFY_KEY来明确启用它，该
        OSCAR_DEPRECATED_ORDER_VERIFY_KEY不能等于SECRET_KEY - 即，自应用此
        更改后，项目必须更改其SECRET_KEY。

        TODO：在Oscar 2.0中弃用此方法，并在Oscar 2.1中删除它。
        """
        old_verification_key = getattr(settings, 'OSCAR_DEPRECATED_ORDER_VERIFY_KEY', None)
        if old_verification_key is None:
            return False

        if old_verification_key == settings.SECRET_KEY:
            raise ImproperlyConfigured(
                'OSCAR_DEPRECATED_ORDER_VERIFY_KEY cannot be equal to SECRET_KEY')

        logger.warning('Using insecure md5 hashing for order URL hash verification.')
        string_to_hash = '%s%s' % (self.number, old_verification_key)
        order_hash = hashlib.md5(string_to_hash.encode('utf8')).hexdigest()
        return constant_time_compare(order_hash, hash_to_check)

    def check_verification_hash(self, hash_to_check):
        """
        Checks the received verification hash against this order number.
        Returns False if the verification failed, True otherwise.
        根据此订单号检查收到的验证哈希。 如果验证失败则返回False，否则返回True。
        """
        if self.check_deprecated_verification_hash(hash_to_check):
            return True

        signer = Signer(salt='oscar.apps.order.Order')
        try:
            signed_number = signer.unsign(hash_to_check)
        except BadSignature:
            return False

        return constant_time_compare(signed_number, self.number)

    @property
    def email(self):
        if not self.user:
            return self.guest_email
        return self.user.email

    @property
    def basket_discounts(self):
        # This includes both offer- and voucher- discounts.  For orders we
        # don't need to treat them differently like we do for baskets.
        # 这包括优惠和优惠折扣。 对于订单，我们不需要像对待篮子那样对待它们。
        return self.discounts.filter(
            category=AbstractOrderDiscount.BASKET)

    @property
    def shipping_discounts(self):
        return self.discounts.filter(
            category=AbstractOrderDiscount.SHIPPING)

    @property
    def post_order_actions(self):
        return self.discounts.filter(
            category=AbstractOrderDiscount.DEFERRED)

    def set_date_placed_default(self):
        if self.date_placed is None:
            self.date_placed = now()

    def save(self, *args, **kwargs):
        # Ensure the date_placed field works as it auto_now_add was set. But
        # this gives us the ability to set the date_placed explicitly (which is
        # useful when importing orders from another system).
        # 确保date_placed字段在设置auto_now_add时有效。 但是这使我们能够明确地
        # 设置date_placed（这在从另一个系统导入订单时很有用）。
        self.set_date_placed_default()
        super().save(*args, **kwargs)


class AbstractOrderNote(models.Model):
    """
    A note against an order.

    This are often used for audit purposes too.  IE, whenever an admin
    makes a change to an order, we create a note to record what happened.
    针对订单的注释
    这通常也用于审计目的。 IE，每当管理员对订单进行更改时，我们都会创建一
    个记录来记录发生的事情。
    """
    order = models.ForeignKey(
        'order.Order',
        on_delete=models.CASCADE,
        related_name="notes",
        verbose_name=_("Order"))

    # These are sometimes programatically generated so don't need a
    # user everytime
    # 这些程序有时是程序生成的，因此不需要用户每次使用。
    user = models.ForeignKey(
        AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        verbose_name=_("User"))

    # We allow notes to be classified although this isn't always needed
    # 我们允许被归类注释虽然这并不总是需要
    INFO, WARNING, ERROR, SYSTEM = 'Info', 'Warning', 'Error', 'System'
    note_type = models.CharField(_("Note Type"), max_length=128, blank=True)

    message = models.TextField(_("Message"))
    date_created = models.DateTimeField(_("Date Created"), auto_now_add=True)
    date_updated = models.DateTimeField(_("Date Updated"), auto_now=True)

    # Notes can only be edited for 5 minutes after being created
    # 注释只能在创建5分钟之后编辑
    editable_lifetime = 300

    class Meta:
        abstract = True
        app_label = 'order'
        verbose_name = _("Order Note")
        verbose_name_plural = _("Order Notes")

    def __str__(self):
        return "'%s' (%s)" % (self.message[0:50], self.user)

    def is_editable(self):
        if self.note_type == self.SYSTEM:
            return False
        delta = timezone.now() - self.date_updated
        return delta.seconds < self.editable_lifetime


class AbstractCommunicationEvent(models.Model):
    """
    An order-level event involving a communication to the customer, such
    as an confirmation email being sent.
    涉及与客户通信的订单级事件，例如正在发送的确认电子邮件。
    """
    order = models.ForeignKey(
        'order.Order',
        on_delete=models.CASCADE,
        related_name="communication_events",
        verbose_name=_("Order"))
    event_type = models.ForeignKey(
        'customer.CommunicationEventType',
        on_delete=models.CASCADE,
        verbose_name=_("Event Type"))
    date_created = models.DateTimeField(_("Date"), auto_now_add=True)

    class Meta:
        abstract = True
        app_label = 'order'
        verbose_name = _("Communication Event")
        verbose_name_plural = _("Communication Events")
        ordering = ['-date_created']

    def __str__(self):
        return _("'%(type)s' event for order #%(number)s") \
            % {'type': self.event_type.name, 'number': self.order.number}


# LINES


class AbstractLine(models.Model):
    """
    An order line 订单行
    """
    order = models.ForeignKey(
        'order.Order',
        on_delete=models.CASCADE,
        related_name='lines',
        verbose_name=_("Order"))

    # PARTNER INFORMATION
    # -------------------
    # We store the partner and various detail their SKU and the title for cases
    # where the product has been deleted from the catalogue (but we still need
    # the data for reporting).  We also store the partner name in case the
    # partner gets deleted at a later date.

    # 合作伙伴信息
    # -------------------
    # 我们存储合作伙伴及其SKU的各种详细信息以及产品已从目录中删除的案例的标
    # 题（但我们仍需要报告数据）。 我们还存储合作伙伴名称，以防合作伙伴在以后被删除。

    partner = models.ForeignKey(
        'partner.Partner', related_name='order_lines', blank=True, null=True,
        on_delete=models.SET_NULL, verbose_name=_("Partner"))
    partner_name = models.CharField(
        _("Partner name"), max_length=128, blank=True)
    partner_sku = models.CharField(_("Partner SKU"), max_length=128)

    # A line reference is the ID that a partner uses to represent this
    # particular line (it's not the same as a SKU).
    # 行引用是合作伙伴用于表示此特定行的ID（它与SKU不同）。
    partner_line_reference = models.CharField(
        _("Partner reference"), max_length=128, blank=True,
        help_text=_("This is the item number that the partner uses "
                    "within their system"))
    partner_line_notes = models.TextField(
        _("Partner Notes"), blank=True)

    # We keep a link to the stockrecord used for this line which allows us to
    # update stocklevels when it ships
    # 我们保留了用于此行的stockrecord的链接，这允许我们在发货时更新库存水平
    stockrecord = models.ForeignKey(
        'partner.StockRecord', on_delete=models.SET_NULL, blank=True,
        null=True, verbose_name=_("Stock record"))

    # PRODUCT INFORMATION
    # -------------------

    # We don't want any hard links between orders and the products table so we
    # allow this link to be NULLable.

    # 产品信息
    # -------------------
    # 我们不希望订单和产品表之间有任何硬链接，因此我们允许此链接为NULL。
    product = models.ForeignKey(
        'catalogue.Product', on_delete=models.SET_NULL, blank=True, null=True,
        verbose_name=_("Product"))
    title = models.CharField(
        pgettext_lazy("Product title", "Title"), max_length=255)
    # UPC can be null because it's usually set as the product's UPC, and that
    # can be null as well
    # UPC可以为null，因为它通常设置为产品的UPC，也可以为null
    # UPC (通用产品代码)
    upc = models.CharField(_("UPC"), max_length=128, blank=True, null=True)

    quantity = models.PositiveIntegerField(_("Quantity"), default=1)

    # REPORTING INFORMATION
    # ---------------------

    # Price information (these fields are actually redundant as the information
    # can be calculated from the LinePrice models)
    # Deprecated - will be removed in Oscar 2.0

    # 报告信息
    # ---------------------
    # 价格信息（这些字段实际上是多余的，因为可以从LinePrice模型计算信息)
    # 已弃用 - 将在Oscar 2.0中删除
    line_price_incl_tax = models.DecimalField(
        _("Price (inc. tax)"), decimal_places=2, max_digits=12)
    # Deprecated - will be removed in Oscar 2.0
    # 已弃用 - 将在Oscar 2.0中删除
    line_price_excl_tax = models.DecimalField(
        _("Price (excl. tax)"), decimal_places=2, max_digits=12)

    # Price information before discounts are applied
    # 折扣前的价格信息
    line_price_before_discounts_incl_tax = models.DecimalField(
        _("Price before discounts (inc. tax)"),
        decimal_places=2, max_digits=12)
    line_price_before_discounts_excl_tax = models.DecimalField(
        _("Price before discounts (excl. tax)"),
        decimal_places=2, max_digits=12)

    # Deprecated - will be removed in Oscar 2.0
    # 已弃用 - 将在Oscar 2.0中删除
    unit_cost_price = models.DecimalField(
        _("Unit Cost Price"), decimal_places=2, max_digits=12, blank=True,
        null=True)
    # Normal site price for item (without discounts)
    # 商品的正常网站价格（不含折扣）
    unit_price_incl_tax = models.DecimalField(
        _("Unit Price (inc. tax)"), decimal_places=2, max_digits=12,
        blank=True, null=True)
    unit_price_excl_tax = models.DecimalField(
        _("Unit Price (excl. tax)"), decimal_places=2, max_digits=12,
        blank=True, null=True)
    # Deprecated - will be removed in Oscar 2.0
    # 已弃用 - 将在Oscar 2.0中删除
    unit_retail_price = models.DecimalField(
        _("Unit Retail Price"), decimal_places=2, max_digits=12,
        blank=True, null=True)

    # Partners often want to assign some status to each line to help with their
    # own business processes.
    # 合作伙伴通常希望为每一行分配一些状态，以帮助他们自己的业务流程。
    status = models.CharField(_("Status"), max_length=255, blank=True)

    # Deprecated - will be removed in Oscar 2.0
    # 已弃用 - 将在Oscar 2.0中删除
    est_dispatch_date = models.DateField(
        _("Estimated Dispatch Date"), blank=True, null=True)

    #: Order status pipeline.  This should be a dict where each (key, value)
    #: corresponds to a status and the possible statuses that can follow that
    #: one.
    # 订单状态管道。 这应该是一个字典，其中每个（键，值）对应一个状态和可能遵
    # 循该状态的可能状态。
    pipeline = getattr(settings, 'OSCAR_LINE_STATUS_PIPELINE', {})

    class Meta:
        abstract = True
        app_label = 'order'
        # Enforce sorting in order of creation.
        # 按创建顺序强制排序。
        ordering = ['pk']
        verbose_name = _("Order Line")
        verbose_name_plural = _("Order Lines")

    def __str__(self):
        if self.product:
            title = self.product.title
        else:
            title = _('<missing product>')
        return _("Product '%(name)s', quantity '%(qty)s'") % {
            'name': title, 'qty': self.quantity}

    @classmethod
    def all_statuses(cls):
        """
        Return all possible statuses for an order line
        返回订单行的所有可能状态
        """
        return list(cls.pipeline.keys())

    def available_statuses(self):
        """
        Return all possible statuses that this order line can move to
        返回此订单行可以移动到的所有可能状态
        """
        return self.pipeline.get(self.status, ())

    def set_status(self, new_status):
        """
        Set a new status for this line

        If the requested status is not valid, then ``InvalidLineStatus`` is
        raised.

        为此行设置新状态
        如果请求的状态无效，则引发“InvalidLineStatus”。
        """
        if new_status == self.status:
            return

        old_status = self.status

        if new_status not in self.available_statuses():
            raise exceptions.InvalidLineStatus(
                _("'%(new_status)s' is not a valid status (current status:"
                  " '%(status)s')")
                % {'new_status': new_status, 'status': self.status})
        self.status = new_status
        self.save()

        # Send signal for handling status changed
        # 发送处理状态改变信号
        order_line_status_changed.send(sender=self,
                                       line=self,
                                       old_status=old_status,
                                       new_status=new_status,
                                       )

    set_status.alters_data = True

    @property
    def description(self):
        """
        Returns a description of this line including details of any
        line attributes.
        返回此行的描述，包括任何行属性的详细信息。
        """
        desc = self.title
        ops = []
        for attribute in self.attributes.all():
            ops.append("%s = '%s'" % (attribute.type, attribute.value))
        if ops:
            desc = "%s (%s)" % (desc, ", ".join(ops))
        return desc

    @property
    def discount_incl_tax(self):
        return self.line_price_before_discounts_incl_tax \
            - self.line_price_incl_tax

    @property
    def discount_excl_tax(self):
        return self.line_price_before_discounts_excl_tax \
            - self.line_price_excl_tax

    @property
    def line_price_tax(self):
        return self.line_price_incl_tax - self.line_price_excl_tax

    @property
    def unit_price_tax(self):
        return self.unit_price_incl_tax - self.unit_price_excl_tax

    # Shipping status helpers 运输状态助手

    @property
    def shipping_status(self):
        """
        Returns a string summary of the shipping status of this line
        返回此行的送货状态的字符串摘要
        """
        status_map = self.shipping_event_breakdown
        if not status_map:
            return ''

        events = []
        last_complete_event_name = None
        for event_dict in reversed(list(status_map.values())):
            if event_dict['quantity'] == self.quantity:
                events.append(event_dict['name'])
                last_complete_event_name = event_dict['name']
            else:
                events.append("%s (%d/%d items)" % (
                    event_dict['name'], event_dict['quantity'],
                    self.quantity))

        if last_complete_event_name == list(status_map.values())[0]['name']:
            return last_complete_event_name

        return ', '.join(events)

    def is_shipping_event_permitted(self, event_type, quantity):
        """
        Test whether a shipping event with the given quantity is permitted

        This method should normally be overriden to ensure that the
        prerequisite shipping events have been passed for this line.

        测试是否允许具有给定数量的装运事件
        通常应覆盖此方法，以确保已为此行传递先决条件运输事件。
        """
        # Note, this calculation is simplistic - normally, you will also need
        # to check if previous shipping events have occurred.  Eg, you can't
        # return lines until they have been shipped.
        # 请注意，此计算过于简单 - 通常，您还需要检查以前的发货事件是否已发
        # 生。 例如，在发货之前，您不能退货。
        current_qty = self.shipping_event_quantity(event_type)
        return (current_qty + quantity) <= self.quantity

    def shipping_event_quantity(self, event_type):
        """
        Return the quantity of this line that has been involved in a shipping
        event of the passed type.
        返回已传递类型的送货事件中涉及的此行的数量。
        """
        result = self.shipping_event_quantities.filter(
            event__event_type=event_type).aggregate(Sum('quantity'))
        if result['quantity__sum'] is None:
            return 0
        else:
            return result['quantity__sum']

    def has_shipping_event_occurred(self, event_type, quantity=None):
        """
        Test whether this line has passed a given shipping event
        测试此行是否已通过给定的送货事件
        """
        if not quantity:
            quantity = self.quantity
        return self.shipping_event_quantity(event_type) == quantity

    def get_event_quantity(self, event):
        """
        Fetches the ShippingEventQuantity instance for this line

        Exists as a separate method so it can be overridden to avoid
        the DB query that's caused by get().

        获取此行的ShippingEventQuantity实例
        作为单独的方法存在，因此可以重写它以避免由get（）引起的数据库查询。
        """
        return event.line_quantities.get(line=self)

    @property
    def shipping_event_breakdown(self):
        """
        Returns a dict of shipping events that this line has been through
        返回此行已通过的航运事件的字典
        """
        status_map = OrderedDict()
        for event in self.shipping_events.all():
            event_type = event.event_type
            event_name = event_type.name
            event_quantity = self.get_event_quantity(event).quantity
            if event_name in status_map:
                status_map[event_name]['quantity'] += event_quantity
            else:
                status_map[event_name] = {
                    'event_type': event_type,
                    'name': event_name,
                    'quantity': event_quantity
                }
        return status_map

    # Payment event helpers 付款事件助手

    def is_payment_event_permitted(self, event_type, quantity):
        """
        Test whether a payment event with the given quantity is permitted.

        Allow each payment event type to occur only once per quantity.

        测试是否允许具有给定数量的付款事件。
        允许每个付款事件类型每个数量仅发生一次。
        """
        current_qty = self.payment_event_quantity(event_type)
        return (current_qty + quantity) <= self.quantity

    def payment_event_quantity(self, event_type):
        """
        Return the quantity of this line that has been involved in a payment
        event of the passed type.
        返回已传递类型的付款事件中涉及的此行的数量。
        """
        result = self.payment_event_quantities.filter(
            event__event_type=event_type).aggregate(Sum('quantity'))
        if result['quantity__sum'] is None:
            return 0
        else:
            return result['quantity__sum']

    @property
    def is_product_deleted(self):
        return self.product is None

    def is_available_to_reorder(self, basket, strategy):
        """
        Test if this line can be re-ordered using the passed strategy and
        basket
        测试是否可以使用已经通过的策略和购物篮重新排序改行
        """
        if not self.product:
            return False, (_("'%(title)s' is no longer available") %
                           {'title': self.title})

        try:
            basket_line = basket.lines.get(product=self.product)
        except basket.lines.model.DoesNotExist:
            desired_qty = self.quantity
        else:
            desired_qty = basket_line.quantity + self.quantity

        result = strategy.fetch_for_product(self.product)
        is_available, reason = result.availability.is_purchase_permitted(
            quantity=desired_qty)
        if not is_available:
            return False, reason
        return True, None


class AbstractLineAttribute(models.Model):
    """
    An attribute of a line
    行属性
    """
    line = models.ForeignKey(
        'order.Line',
        on_delete=models.CASCADE,
        related_name='attributes',
        verbose_name=_("Line"))
    option = models.ForeignKey(
        'catalogue.Option', null=True, on_delete=models.SET_NULL,
        related_name="line_attributes", verbose_name=_("Option"))
    type = models.CharField(_("Type"), max_length=128)
    value = models.CharField(_("Value"), max_length=255)

    class Meta:
        abstract = True
        app_label = 'order'
        verbose_name = _("Line Attribute")
        verbose_name_plural = _("Line Attributes")

    def __str__(self):
        return "%s = %s" % (self.type, self.value)


class AbstractLinePrice(models.Model):
    """
    For tracking the prices paid for each unit within a line.

    This is necessary as offers can lead to units within a line
    having different prices.  For example, one product may be sold at
    50% off as it's part of an offer while the remainder are full price.

    用于跟踪一行内每个单元的价格。
    这是必要的，因为报价可能导致一条线内的单位具有不同的价格。 例如，一种
    产品可以50％的价格出售，因为它是报价的一部分，而其余的是全价。
    """
    order = models.ForeignKey(
        'order.Order',
        on_delete=models.CASCADE,
        related_name='line_prices',
        verbose_name=_("Option"))
    line = models.ForeignKey(
        'order.Line',
        on_delete=models.CASCADE,
        related_name='prices',
        verbose_name=_("Line"))
    quantity = models.PositiveIntegerField(_("Quantity"), default=1)
    price_incl_tax = models.DecimalField(
        _("Price (inc. tax)"), decimal_places=2, max_digits=12)
    price_excl_tax = models.DecimalField(
        _("Price (excl. tax)"), decimal_places=2, max_digits=12)
    shipping_incl_tax = models.DecimalField(
        _("Shiping (inc. tax)"), decimal_places=2, max_digits=12, default=0)
    shipping_excl_tax = models.DecimalField(
        _("Shipping (excl. tax)"), decimal_places=2, max_digits=12, default=0)

    class Meta:
        abstract = True
        app_label = 'order'
        ordering = ('id',)
        verbose_name = _("Line Price")
        verbose_name_plural = _("Line Prices")

    def __str__(self):
        return _("Line '%(number)s' (quantity %(qty)d) price %(price)s") % {
            'number': self.line,
            'qty': self.quantity,
            'price': self.price_incl_tax}


# PAYMENT EVENTS 付款事件


class AbstractPaymentEventType(models.Model):
    """
    Payment event types are things like 'Paid', 'Failed', 'Refunded'.

    These are effectively the transaction types.

    付款事件类型包括“付费”，“失败”，“退款”等。
    这些实际上是交易类型。
    """
    name = models.CharField(_("Name"), max_length=128, unique=True)
    code = AutoSlugField(_("Code"), max_length=128, unique=True,
                         populate_from='name')

    class Meta:
        abstract = True
        app_label = 'order'
        verbose_name = _("Payment Event Type")
        verbose_name_plural = _("Payment Event Types")
        ordering = ('name', )

    def __str__(self):
        return self.name


class AbstractPaymentEvent(models.Model):
    """
    A payment event for an order

    For example:

    * All lines have been paid for
    * 2 lines have been refunded

    订单的付款事件
    例如：
    * 所有行都已付款
    * 2行已退款
    """
    order = models.ForeignKey(
        'order.Order',
        on_delete=models.CASCADE,
        related_name='payment_events',
        verbose_name=_("Order"))
    amount = models.DecimalField(
        _("Amount"), decimal_places=2, max_digits=12)
    # The reference should refer to the transaction ID of the payment gateway
    # that was used for this event.
    # 该引用应该引用用于此事件的支付网关的事务ID。
    reference = models.CharField(
        _("Reference"), max_length=128, blank=True)
    lines = models.ManyToManyField(
        'order.Line', through='PaymentEventQuantity',
        verbose_name=_("Lines"))
    event_type = models.ForeignKey(
        'order.PaymentEventType',
        on_delete=models.CASCADE,
        verbose_name=_("Event Type"))
    # Allow payment events to be linked to shipping events.  Often a shipping
    # event will trigger a payment event and so we can use this FK to capture
    # the relationship.
    # 允许将付款事件与送货事件相关联。 航运事件通常会触发付款事件，因此我们
    # 可以使用此FK来捕获关系。
    shipping_event = models.ForeignKey(
        'order.ShippingEvent',
        null=True,
        on_delete=models.CASCADE,
        related_name='payment_events')
    date_created = models.DateTimeField(_("Date created"), auto_now_add=True)

    class Meta:
        abstract = True
        app_label = 'order'
        verbose_name = _("Payment Event")
        verbose_name_plural = _("Payment Events")
        ordering = ['-date_created']

    def __str__(self):
        return _("Payment event for order %s") % self.order

    def num_affected_lines(self):
        return self.lines.all().count()


class PaymentEventQuantity(models.Model):
    """
    A "through" model linking lines to payment events
    链接到支付事件的“through”模型
    """
    event = models.ForeignKey(
        'order.PaymentEvent',
        on_delete=models.CASCADE,
        related_name='line_quantities',
        verbose_name=_("Event"))
    line = models.ForeignKey(
        'order.Line',
        on_delete=models.CASCADE,
        related_name="payment_event_quantities",
        verbose_name=_("Line"))
    quantity = models.PositiveIntegerField(_("Quantity"))

    class Meta:
        app_label = 'order'
        verbose_name = _("Payment Event Quantity")
        verbose_name_plural = _("Payment Event Quantities")
        unique_together = ('event', 'line')


# SHIPPING EVENTS 运输事件


class AbstractShippingEvent(models.Model):
    """
    An event is something which happens to a group of lines such as
    1 item being dispatched.
    事件是在一组行中发生的事情，例如被调度的1个项目。
    """
    order = models.ForeignKey(
        'order.Order',
        on_delete=models.CASCADE,
        related_name='shipping_events',
        verbose_name=_("Order"))
    lines = models.ManyToManyField(
        'order.Line', related_name='shipping_events',
        through='ShippingEventQuantity', verbose_name=_("Lines"))
    event_type = models.ForeignKey(
        'order.ShippingEventType',
        on_delete=models.CASCADE,
        verbose_name=_("Event Type"))
    notes = models.TextField(
        _("Event notes"), blank=True,
        help_text=_("This could be the dispatch reference, or a "
                    "tracking number"))
    date_created = models.DateTimeField(_("Date Created"), auto_now_add=True)

    class Meta:
        abstract = True
        app_label = 'order'
        verbose_name = _("Shipping Event")
        verbose_name_plural = _("Shipping Events")
        ordering = ['-date_created']

    def __str__(self):
        return _("Order #%(number)s, type %(type)s") % {
            'number': self.order.number,
            'type': self.event_type}

    def num_affected_lines(self):
        return self.lines.count()


class ShippingEventQuantity(models.Model):
    """
    A "through" model linking lines to shipping events.

    This exists to track the quantity of a line that is involved in a
    particular shipping event.

    “thorough”模型将行与运输事件联系起来。
    这用于跟踪特定运输事件中涉及的行的数量。
    """
    event = models.ForeignKey(
        'order.ShippingEvent',
        on_delete=models.CASCADE,
        related_name='line_quantities',
        verbose_name=_("Event"))
    line = models.ForeignKey(
        'order.Line',
        on_delete=models.CASCADE,
        related_name="shipping_event_quantities",
        verbose_name=_("Line"))
    quantity = models.PositiveIntegerField(_("Quantity"))

    class Meta:
        app_label = 'order'
        verbose_name = _("Shipping Event Quantity")
        verbose_name_plural = _("Shipping Event Quantities")
        unique_together = ('event', 'line')

    def save(self, *args, **kwargs):
        # Default quantity to full quantity of line
        # 默认数量为行数量
        if not self.quantity:
            self.quantity = self.line.quantity
        # Ensure we don't violate quantities constraint
        # 确保我们不违反数量限制
        if not self.line.is_shipping_event_permitted(
                self.event.event_type, self.quantity):
            raise exceptions.InvalidShippingEvent
        super().save(*args, **kwargs)

    def __str__(self):
        return _("%(product)s - quantity %(qty)d") % {
            'product': self.line.product,
            'qty': self.quantity}


class AbstractShippingEventType(models.Model):
    """
    A type of shipping/fulfillment event

    Eg: 'Shipped', 'Cancelled', 'Returned'

    一种运输/履行事件
    例如：'已发货'，'已取消'，'已退回'
    """
    # Name is the friendly description of an event
    # 名称是对事件的友好描述
    name = models.CharField(_("Name"), max_length=255, unique=True)
    # Code is used in forms
    # 代码用于表单
    code = AutoSlugField(_("Code"), max_length=128, unique=True,
                         populate_from='name')

    class Meta:
        abstract = True
        app_label = 'order'
        verbose_name = _("Shipping Event Type")
        verbose_name_plural = _("Shipping Event Types")
        ordering = ('name', )

    def __str__(self):
        return self.name


# DISCOUNTS 折扣


class AbstractOrderDiscount(models.Model):
    """
    A discount against an order.

    Normally only used for display purposes so an order can be listed with
    discounts displayed separately even though in reality, the discounts are
    applied at the line level.

    This has evolved to be a slightly misleading class name as this really
    track benefit applications which aren't necessarily discounts.

    对订单的折扣。
    通常仅用于显示目的，因此可以列出具有单独显示的折扣的订单，即使实际
    上，折扣也在行级应用。
    这已经发展成为一个有点误导性的类名，因为这实际上跟踪了不一定是折扣的福利申请。
    """
    order = models.ForeignKey(
        'order.Order',
        on_delete=models.CASCADE,
        related_name="discounts",
        verbose_name=_("Order"))

    # We need to distinguish between basket discounts, shipping discounts and
    # 'deferred' discounts.
    # 我们需要区分购物篮折扣，运费折扣和“deferred”折扣。
    BASKET, SHIPPING, DEFERRED = "Basket", "Shipping", "Deferred"
    CATEGORY_CHOICES = (
        (BASKET, _(BASKET)),
        (SHIPPING, _(SHIPPING)),
        (DEFERRED, _(DEFERRED)),
    )
    category = models.CharField(
        _("Discount category"), default=BASKET, max_length=64,
        choices=CATEGORY_CHOICES)

    offer_id = models.PositiveIntegerField(
        _("Offer ID"), blank=True, null=True)
    offer_name = models.CharField(
        _("Offer name"), max_length=128, db_index=True, blank=True)
    voucher_id = models.PositiveIntegerField(
        _("Voucher ID"), blank=True, null=True)
    voucher_code = models.CharField(
        _("Code"), max_length=128, db_index=True, blank=True)
    frequency = models.PositiveIntegerField(_("Frequency"), null=True)
    amount = models.DecimalField(
        _("Amount"), decimal_places=2, max_digits=12, default=0)

    # Post-order offer applications can return a message to indicate what
    # action was taken after the order was placed.
    # 订单后报价应用程序可以返回一条消息，指示订单下达后采取的操作。
    message = models.TextField(blank=True)

    @property
    def is_basket_discount(self):
        return self.category == self.BASKET

    @property
    def is_shipping_discount(self):
        return self.category == self.SHIPPING

    @property
    def is_post_order_action(self):
        return self.category == self.DEFERRED

    class Meta:
        abstract = True
        app_label = 'order'
        verbose_name = _("Order Discount")
        verbose_name_plural = _("Order Discounts")

    def save(self, **kwargs):
        if self.offer_id and not self.offer_name:
            offer = self.offer
            if offer:
                self.offer_name = offer.name

        if self.voucher_id and not self.voucher_code:
            voucher = self.voucher
            if voucher:
                self.voucher_code = voucher.code

        super().save(**kwargs)

    def __str__(self):
        return _("Discount of %(amount)r from order %(order)s") % {
            'amount': self.amount, 'order': self.order}

    @property
    def offer(self):
        Offer = get_model('offer', 'ConditionalOffer')
        try:
            return Offer.objects.get(id=self.offer_id)
        except Offer.DoesNotExist:
            return None

    @property
    def voucher(self):
        Voucher = get_model('voucher', 'Voucher')
        try:
            return Voucher.objects.get(id=self.voucher_id)
        except Voucher.DoesNotExist:
            return None

    def description(self):
        if self.voucher_code:
            return self.voucher_code
        return self.offer_name or ""
