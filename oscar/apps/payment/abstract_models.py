from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _

from oscar.core.compat import AUTH_USER_MODEL
from oscar.core.utils import get_default_currency
from oscar.models.fields import AutoSlugField
from oscar.templatetags.currency_filters import currency

from . import bankcards


class AbstractTransaction(models.Model):
    """
    A transaction for a particular payment source.

    These are similar to the payment events within the order app but model a
    slightly different aspect of payment.  Crucially, payment sources and
    transactions have nothing to do with the lines of the order while payment
    events do.

    For example:
    * A 'pre-auth' with a bankcard gateway
    * A 'settle' with a credit provider (see django-oscar-accounts)

    特定付款来源的交易。
    这些类似于订单应用程序中的付款事件，但模型略有不同的付款方面。 至关重要的
    是，付款来源和交易与付款事件的订单行无关。
    例如：
    * 带有银行卡网关的'pre-auth(预授权)'
    * 与信贷提供者'结算'（参见django-oscar-accounts）
    """
    source = models.ForeignKey(
        'payment.Source',
        on_delete=models.CASCADE,
        related_name='transactions',
        verbose_name=_("Source"))

    # We define some sample types but don't constrain txn_type to be one of
    # these as there will be domain-specific ones that we can't anticipate
    # here.
    # 我们定义了一些样本类型，但没有将txn_type限制为其中之一，因为我们无法
    # 在这里预测特定于域的类型。
    AUTHORISE, DEBIT, REFUND = 'Authorise', 'Debit', 'Refund'
    txn_type = models.CharField(_("Type"), max_length=128, blank=True)

    amount = models.DecimalField(_("Amount"), decimal_places=2, max_digits=12)
    reference = models.CharField(_("Reference"), max_length=128, blank=True)
    status = models.CharField(_("Status"), max_length=128, blank=True)
    date_created = models.DateTimeField(_("Date Created"), auto_now_add=True)

    def __str__(self):
        return _("%(type)s of %(amount).2f") % {
            'type': self.txn_type,
            'amount': self.amount}

    class Meta:
        abstract = True
        app_label = 'payment'
        ordering = ['-date_created']
        verbose_name = _("Transaction")
        verbose_name_plural = _("Transactions")


class AbstractSource(models.Model):
    """
    A source of payment for an order.

    This is normally a credit card which has been pre-authed for the order
    amount, but some applications will allow orders to be paid for using
    multiple sources such as cheque, credit accounts, gift cards.  Each payment
    source will have its own entry.

    This source object tracks how much money has been authorised, debited and
    refunded, which is useful when payment takes place in multiple stages.

    订单的付款来源。

    这通常是一张信用卡，已经为订单金额预先兑现，但是一些应用程序将允许使用多种
    来源（如支票，信用卡，礼品卡）支付订单。 每个付款来源都有自己的条目。

    此源对象跟踪已授权，借记和退款的金额，这在多个阶段进行付款时非常有用
    """
    order = models.ForeignKey(
        'order.Order',
        on_delete=models.CASCADE,
        related_name='sources',
        verbose_name=_("Order"))
    source_type = models.ForeignKey(
        'payment.SourceType',
        on_delete=models.CASCADE,
        related_name="sources",
        verbose_name=_("Source Type"))
    currency = models.CharField(
        _("Currency"), max_length=12, default=get_default_currency)

    # Track the various amounts associated with this source
    # 跟踪与此来源相关的各种金额
    amount_allocated = models.DecimalField(
        _("Amount Allocated"), decimal_places=2, max_digits=12,
        default=Decimal('0.00'))
    amount_debited = models.DecimalField(
        _("Amount Debited"), decimal_places=2, max_digits=12,
        default=Decimal('0.00'))
    amount_refunded = models.DecimalField(
        _("Amount Refunded"), decimal_places=2, max_digits=12,
        default=Decimal('0.00'))

    # Reference number for this payment source.  This is often used to look up
    # a transaction model for a particular payment partner.
    # 此付款来源的参考号。 这通常用于查找特定付款合作伙伴的交易模型。
    reference = models.CharField(_("Reference"), max_length=255, blank=True)

    # A customer-friendly label for the source, eg XXXX-XXXX-XXXX-1234
    # 源的客户友好标签，例如XXXX-XXXX-XXXX-1234
    label = models.CharField(_("Label"), max_length=128, blank=True)

    # A dictionary of submission data that is stored as part of the
    # checkout process, where we need to pass an instance of this class around
    # 提交数据字典，作为结帐过程的一部分存储，我们需要传递此类的实例
    submission_data = None

    # We keep a list of deferred transactions that are only actually saved when
    # the source is saved for the first time
    # 我们保留了一个仅在第一次保存源时才实际保存的延迟事务列表
    deferred_txns = None

    class Meta:
        abstract = True
        app_label = 'payment'
        verbose_name = _("Source")
        verbose_name_plural = _("Sources")

    def __str__(self):
        description = _("Allocation of %(amount)s from type %(type)s") % {
            'amount': currency(self.amount_allocated, self.currency),
            'type': self.source_type}
        if self.reference:
            description += _(" (reference: %s)") % self.reference
        return description

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.deferred_txns:
            for txn in self.deferred_txns:
                self._create_transaction(*txn)

    def create_deferred_transaction(self, txn_type, amount, reference=None,
                                    status=None):
        """
        Register the data for a transaction that can't be created yet due to FK
        constraints.  This happens at checkout where create an payment source
        and a transaction but can't save them until the order model exists.
        注册由于FK约束而无法创建的事务的数据。 这在结帐处发生，其中创建支付来源
        和交易，但在订单模型存在之前无法保存。
        """
        if self.deferred_txns is None:
            self.deferred_txns = []
        self.deferred_txns.append((txn_type, amount, reference, status))

    def _create_transaction(self, txn_type, amount, reference='',
                            status=''):
        self.transactions.create(
            txn_type=txn_type, amount=amount,
            reference=reference, status=status)

    # =======
    # Actions 操作
    # =======

    def allocate(self, amount, reference='', status=''):
        """
        Convenience method for ring-fencing money against this source
        对这个来源进行围栏资金的便捷方法
        """
        self.amount_allocated += amount
        self.save()
        self._create_transaction(
            AbstractTransaction.AUTHORISE, amount, reference, status)
    allocate.alters_data = True

    def debit(self, amount=None, reference='', status=''):
        """
        Convenience method for recording debits against this source
        方便记录借方的方法
        """
        if amount is None:
            amount = self.balance
        self.amount_debited += amount
        self.save()
        self._create_transaction(
            AbstractTransaction.DEBIT, amount, reference, status)
    debit.alters_data = True

    def refund(self, amount, reference='', status=''):
        """
        Convenience method for recording refunds against this source
        记录针对此来源的退款的便捷方法
        """
        self.amount_refunded += amount
        self.save()
        self._create_transaction(
            AbstractTransaction.REFUND, amount, reference, status)
    refund.alters_data = True

    # ==========
    # Properties 属性
    # ==========

    @property
    def balance(self):
        """
        Return the balance of this source
        返回此来源的余额
        """
        return (self.amount_allocated - self.amount_debited +
                self.amount_refunded)

    @property
    def amount_available_for_refund(self):
        """
        Return the amount available to be refunded
        退还可退款金额
        """
        return self.amount_debited - self.amount_refunded


class AbstractSourceType(models.Model):
    """
    A type of payment source.

    This could be an external partner like PayPal or DataCash,
    or an internal source such as a managed account.

    一种付款来源。
    这可以是PayPal或DataCash等外部合作伙伴，也可以是托管帐户等内部来源。
    """
    name = models.CharField(_("Name"), max_length=128)
    code = AutoSlugField(
        _("Code"), max_length=128, populate_from='name', unique=True,
        help_text=_("This is used within forms to identify this source type"))

    class Meta:
        abstract = True
        app_label = 'payment'
        verbose_name = _("Source Type")
        verbose_name_plural = _("Source Types")

    def __str__(self):
        return self.name


class AbstractBankcard(models.Model):
    """
    Model representing a user's bankcard.  This is used for two purposes:

        1.  The bankcard form will return an instance of this model that can be
            used with payment gateways.  In this scenario, the instance will
            have additional attributes (start_date, issue_number, ccv) that
            payment gateways need but that we don't save.

        2.  To keep a record of a user's bankcards and allow them to be
            re-used.  This is normally done using the 'partner reference'.

    .. warning::

        Some of the fields of this model (name, expiry_date) are considered
        "cardholder data" under PCI DSS v2. Hence, if you use this model and
        store those fields then the requirements for PCI compliance will be
        more stringent.

    代表用户的银行卡的模型。 这用于两个目的：
        1.银行卡表格将返回此模型的一个实例，该实例可用于支付网关。 在这种情况
        下，实例将具有支付网关需要但我们不保存的其他属性（start_date，issue_number，ccv）。
        2.记录用户的银行卡并允许重复使用。 这通常使用“合作伙伴参考”完成。
        警告：：
        此模型的某些字段（name，expiry_date）在PCI DSS v2下被视为“持卡人数据”。
        因此，如果您使用此模型并存储这些字段，那么PCI合规性的要求将更加严格。
    """
    user = models.ForeignKey(
        AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='bankcards',
        verbose_name=_("User"))
    card_type = models.CharField(_("Card Type"), max_length=128)

    # Often you don't actually need the name on the bankcard
    # 通常，您实际上并不需要银行卡上的名称
    name = models.CharField(_("Name"), max_length=255, blank=True)

    # We store an obfuscated version of the card number, just showing the last
    # 4 digits.
    # 我们存储了卡号的混淆版本，只显示最后4位数字。
    number = models.CharField(_("Number"), max_length=32)

    # We store a date even though only the month is visible.  Bankcards are
    # valid until the last day of the month.
    # 我们存储日期，即使只有月份可见。 银行卡有效期至该月的最后一天。
    expiry_date = models.DateField(_("Expiry Date"))

    # For payment partners who are storing the full card details for us
    # 对于为我们存储完整卡详细信息的付款合作伙伴
    partner_reference = models.CharField(
        _("Partner Reference"), max_length=255, blank=True)

    # Temporary data not persisted to the DB
    # 临时数据不保存到数据库中
    start_date = None
    issue_number = None
    ccv = None

    def __str__(self):
        return _("%(card_type)s %(number)s (Expires: %(expiry)s)") % {
            'card_type': self.card_type,
            'number': self.number,
            'expiry': self.expiry_month()}

    def __init__(self, *args, **kwargs):
        # Pop off the temporary data
        # 弹出临时数据
        self.start_date = kwargs.pop('start_date', None)
        self.issue_number = kwargs.pop('issue_number', None)
        self.ccv = kwargs.pop('ccv', None)
        super().__init__(*args, **kwargs)

        # Initialise the card-type
        # 初始化卡片类型
        if self.id is None:
            self.card_type = bankcards.bankcard_type(self.number)
            if self.card_type is None:
                self.card_type = 'Unknown card type'

    class Meta:
        abstract = True
        app_label = 'payment'
        verbose_name = _("Bankcard")
        verbose_name_plural = _("Bankcards")

    def save(self, *args, **kwargs):
        if not self.number.startswith('X'):
            self.prepare_for_save()
        super().save(*args, **kwargs)

    def prepare_for_save(self):
        # This is the first time this card instance is being saved.  We
        # remove all sensitive data
        # 这是第一次保存此卡实例。 我们删除所有敏感数据
        self.number = "XXXX-XXXX-XXXX-%s" % self.number[-4:]
        self.start_date = self.issue_number = self.ccv = None

    @property
    def cvv(self):
        return self.ccv

    @property
    def obfuscated_number(self):
        return 'XXXX-XXXX-XXXX-%s' % self.number[-4:]

    def start_month(self, format='%m/%y'):
        return self.start_date.strftime(format)

    def expiry_month(self, format='%m/%y'):
        return self.expiry_date.strftime(format)
