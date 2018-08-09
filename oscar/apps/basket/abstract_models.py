import zlib
from decimal import Decimal as D

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.db import models
from django.db.models import Sum
from django.utils.encoding import smart_text
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _

from oscar.core.compat import AUTH_USER_MODEL
from oscar.core.loading import get_class, get_classes
from oscar.core.utils import get_default_currency
from oscar.models.fields.slugfield import SlugField
from oscar.templatetags.currency_filters import currency

# 提供应用程序
OfferApplications = get_class('offer.results', 'OfferApplications')
# 不可用的
Unavailable = get_class('partner.availability', 'Unavailable')
# 线报用户
LineOfferConsumer = get_class('basket.utils', 'LineOfferConsumer')
# 打开、关闭购物篮管理器
OpenBasketManager, SavedBasketManager = get_classes('basket.managers', ['OpenBasketManager', 'SavedBasketManager'])


# 抽象购物篮（生成购物车类)
class AbstractBasket(models.Model):
    """
    Basket object 购物篮 类
    """
    # Baskets can be anonymously owned - hence this field is nullable.  When a
    # anon user signs in, their two baskets are merged.
    # 购物篮可以匿名拥有，因此这个字段是空的，当用户登录时，他们的两个购物车将会合并。

    # 物主
    owner = models.ForeignKey(
        AUTH_USER_MODEL,
        null=True,
        related_name='baskets',
        on_delete=models.CASCADE,
        verbose_name=_("Owner"))

    # Basket statuses
    # - Frozen is for when a basket is in the process of being submitted
    #   and we need to prevent any changes to it.
    # 购物车状态
    # -Frozen 冻结 是指当购物篮被提交的过程中我们需要阻止它的任何改变。

    # 打开、合并、保存、冻结、提交
    OPEN, MERGED, SAVED, FROZEN, SUBMITTED = (
        "Open", "Merged", "Saved", "Frozen", "Submitted")
    STATUS_CHOICES = (
        (OPEN, _("Open - currently active")),
        (MERGED, _("Merged - superceded by another basket")),
        (SAVED, _("Saved - for items to be purchased later")),
        (FROZEN, _("Frozen - the basket cannot be modified")),
        (SUBMITTED, _("Submitted - has been ordered at the checkout")),
    )
    status = models.CharField(
        _("Status"), max_length=128, default=OPEN, choices=STATUS_CHOICES)

    # A basket can have many vouchers attached to it.  However, it is common
    # for sites to only allow one voucher per basket - this will need to be
    # enforced in the project's codebase.
    # 购物篮可以有很多券附在上面。然而，网站通常只允许一个券每篮子-
    # 这将需要在项目的代码库中执行。
    vouchers = models.ManyToManyField(
        'voucher.Voucher', verbose_name=_("Vouchers"), blank=True)
    # 生成
    date_created = models.DateTimeField(_("Date created"), auto_now_add=True)
    # 合并
    date_merged = models.DateTimeField(_("Date merged"), null=True, blank=True)
    # 提交
    date_submitted = models.DateTimeField(_("Date submitted"), null=True,
                                          blank=True)

    # Only if a basket is in one of these statuses can it be edited
    # 只有购物篮在这些状态中才能编辑
    editable_statuses = (OPEN, SAVED) # editable statuses

    class Meta:
        abstract = True
        app_label = 'basket'
        verbose_name = _('Basket')
        verbose_name_plural = _('Baskets')

    objects = models.Manager()
    open = OpenBasketManager()
    saved = SavedBasketManager()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # We keep a cached copy of the basket lines as we refer to them often
        # within the same request cycle.  Also, applying offers will append
        # discount data to the basket lines which isn't persisted to the DB and
        # so we want to avoid reloading them as this would drop the discount
        # information.
        # 我们保持购物篮的缓存副本，因为我们经常提到它们在相同的请求周期内。
        # 此外，应用报价将附加折扣数据到购物篮，这是不坚持到数据库，
        # 所以我们希望避免重新加载它们，因为这将降低数据信息。
        self._lines = None
        self.offer_applications = OfferApplications()

    def __str__(self):
        return _(
            "%(status)s basket (owner: %(owner)s, lines: %(num_lines)d)") \
            % {'status': self.status,
               'owner': self.owner,
               'num_lines': self.num_lines}

    # ========
    # Strategy 策略，规划；部署；统筹安排
    # ========

    @property   # 属性
    def has_strategy(self):
        return hasattr(self, '_strategy')

    def _get_strategy(self):
        if not self.has_strategy:
            raise RuntimeError(
                "No strategy class has been assigned to this basket. "
                "This is normally assigned to the incoming request in "
                "oscar.apps.basket.middleware.BasketMiddleware. "
                "Since it is missing, you must be doing something different. "
                "Ensure that a strategy instance is assigned to the basket!"
            )
        # 没有一个策略类被分配给这个购物篮。这通常被分配给oscar.apps.basket.middleware.BasketMiddleware.
        # 传入请求，
        # 因为它丢失了，你必须做一些不同的事情。确保将一个策略实例分配给购物篮！
        return self._strategy

    def _set_strategy(self, strategy):
        self._strategy = strategy

    strategy = property(_get_strategy, _set_strategy)

    def all_lines(self):
        """
        Return a cached set of basket lines.

        This is important for offers as they alter the line models and you
        don't want to reload them from the DB as that information would be
        lost.
        """
        # 返回一组缓存的购物篮数据
        # 这是重要的，因为他们改变了线模型，你不从数据库重新加载他们，这些信息将丢失。
        if self.id is None:
            return self.lines.none()
        if self._lines is None:
            self._lines = (
                self.lines
                .select_related('product', 'stockrecord')
                .prefetch_related(
                    'attributes', 'product__images')
                .order_by(self._meta.pk.name))
        return self._lines

    def max_allowed_quantity(self):
        """
        Returns maximum product quantity, that can be added to the basket
        with the respect to basket quantity threshold.
        """
        # 返回最大产品数量，可添加数量要遵从购物篮的最大值（阀值）
        basket_threshold = settings.OSCAR_MAX_BASKET_QUANTITY_THRESHOLD
        if basket_threshold:
            total_basket_quantity = self.num_items
            max_allowed = basket_threshold - total_basket_quantity
            return max_allowed, basket_threshold
        return None, None

    def is_quantity_allowed(self, qty):
        """
        Test whether the passed quantity of items can be added to the basket
        """
        # 测试是否可以将项目的数量添加到购物篮中

        # We enforce a max threshold to prevent a DOS attack via the offers
        # system.
        # 我们执行最大阈值，以防止DoS攻击通过报价系统

        # 允许最大值，购物篮阀值            最大允许量
        max_allowed, basket_threshold = self.max_allowed_quantity()
        if max_allowed is not None and qty > max_allowed:
            return False, _(
                "Due to technical limitations we are not able "
                "to ship more than %(threshold)d items in one order.") \
                % {'threshold': basket_threshold}
        # 由于技术限制，我们不能以一个顺序运送超过%（阈值）D项。
        return True, None

    # ============
    # Manipulation 控制
    # ============

    def flush(self):
        """
        Remove all lines from basket.
        """
        # 从购物车移除所有行
        if self.status == self.FROZEN:
            # 冻结的购物篮不能清空
            raise PermissionDenied("A frozen basket cannot be flushed")
        self.lines.all().delete()
        self._lines = None

    # 获取库存信息
    def get_stock_info(self, product, options):
        """
        Hook for implementing strategies that depend on product options
        """
        # 策略取决于产品选项

        # The built-in strategies don't use options, so initially disregard
        # them.
        # 内置策略不使用选项，所以最初忽略它们。

        return self.strategy.fetch_for_product(product)

    # 添加产品
    def add_product(self, product, quantity=1, options=None):
        """
        Add a product to the basket

        The 'options' list should contains dicts with keys 'option' and 'value'
        which link the relevant product.Option model and string value
        respectively.

        Returns (line, created).
          line: the matching basket line
          created: whether the line was created or updated

        """
        # 添加产品到购物篮
        # “选项”列表应该包含DITCS，其中键“选项”和“值”分别链接相关产品、选项模型和字符串值。
        # 返回值（ 行，创建)
        # 行：与购物篮匹配的行
        # 创建：是否创建或更新了该行
        if options is None:
            options = []
        if not self.id:
            self.save()

        # Ensure that all lines are the same currency
        # 确保所有的行都是相同的货币
        price_currency = self.currency
        stock_info = self.get_stock_info(product, options)

        if not stock_info.price.exists:
            # 策略尚未发现产品价格
            raise ValueError(
                "Strategy hasn't found a price for product %s" % product)

        if price_currency and stock_info.price.currency != price_currency:
            # 购物篮中的物品必须使用相同的货币，建议
            raise ValueError((
                "Basket lines must all have the same currency. Proposed "
                "line has currency %s, while basket has currency %s")
                % (stock_info.price.currency, price_currency))

        if stock_info.stockrecord is None:
            # 购物篮必须用库存记录，策略没发现任何产品的库存记录
            raise ValueError((
                "Basket lines must all have stock records. Strategy hasn't "
                "found any stock record for product %s") % product)

        # Line reference is used to distinguish between variations of the same
        # product (eg T-shirts with different personalisations)
        # 行 基准是用来区分同一变化的。
        # 产品（如不同个性的T恤）
        line_ref = self._create_line_reference(
            product, stock_info.stockrecord, options)

        # Determine price to store (if one exists).  It is only stored for
        # audit and sometimes caching.
        # 确定价格存储（如果存在的话）。它只存储用于审计和有时缓存。
        defaults = {
            'quantity': quantity,
            'price_excl_tax': stock_info.price.excl_tax,
            'price_currency': stock_info.price.currency,
        }
        if stock_info.price.is_tax_known:
            defaults['price_incl_tax'] = stock_info.price.incl_tax

        line, created = self.lines.get_or_create(
            line_reference=line_ref,
            product=product,
            stockrecord=stock_info.stockrecord,
            defaults=defaults)
        if created:
            for option_dict in options:
                line.attributes.create(option=option_dict['option'],
                                       value=option_dict['value'])
        else:
            line.quantity = max(0, line.quantity + quantity)
            line.save()
        self.reset_offer_applications()

        # Returning the line is useful when overriding this method.
        # 当重写此方法时，返回行是有用的。
        return line, created
    add_product.alters_data = True
    add = add_product

# 应用报价
    def applied_offers(self):
        """
        Return a dict of offers successfully applied to the basket.

        This is used to compare offers before and after a basket change to see
        if there is a difference.

        返回一个成功地购物篮下的报价应用。
        这是用来比较购物篮之前和之后的变化，看看是否有差异。
        """
        return self.offer_applications.offers

    # 重置报价应用程序
    def reset_offer_applications(self):
        """
        Remove any discounts so they get recalculated
        删除任何折扣，以便重新计算
        """
        self.offer_applications = OfferApplications()
        self._lines = None

    def merge_line(self, line, add_quantities=True):
        """
        For transferring a line from another basket to this one.

        This is used with the "Saved" basket functionality.

        把一个行 从另一个购物篮 转移到这个购物篮
        这与“保存”购物篮 功能一起使用。

        """
        try:
            existing_line = self.lines.get(line_reference=line.line_reference)
        except ObjectDoesNotExist:
            # Line does not already exist - reassign its basket
            # 行不存在 重新分配它的购物篮
            line.basket = self
            line.save()
        else:
            # Line already exists - assume the max quantity is correct and
            # delete the old
            # 行已经存在-假设最大数量是正确的并且删除旧的
            if add_quantities:
                existing_line.quantity += line.quantity
            else:
                existing_line.quantity = max(existing_line.quantity,
                                             line.quantity)
            existing_line.save()
            line.delete()
        finally:
            self._lines = None
    merge_line.alters_data = True

    # merge 合并
    def merge(self, basket, add_quantities=True):
        """
        Merges another basket with this one.

        :basket: The basket to merge into this one.
        :add_quantities: Whether to add line quantities when they are merged.

        把一个购物篮和这个购物篮合并
        :购物篮: 购物篮合并成这一个.
        :添加数量: 是否在合并时添加行量

        """
        # Use basket.lines.all instead of all_lines as this function is called
        # before a strategy has been assigned.
        # 在分配策略之前调用该函数，而不是使用all_lines

        for line_to_merge in basket.lines.all():
            self.merge_line(line_to_merge, add_quantities)
        basket.status = self.MERGED
        basket.date_merged = now()
        basket._lines = None
        basket.save()
        # Ensure all vouchers are moved to the new basket
        # 确保所有凭证都移到新的购物篮里。
        for voucher in basket.vouchers.all():
            basket.vouchers.remove(voucher)
            self.vouchers.add(voucher)
    merge.alters_data = True

    # freeze 冻结
    def freeze(self):
        """
        Freezes the basket so it cannot be modified.
        冻结购物篮不能修改
        """
        self.status = self.FROZEN
        self.save()
    freeze.alters_data = True

    # thaw 解冻
    def thaw(self):
        """
        Unfreezes a basket so it can be modified again
        解冻一个购物篮，这样它可以再次被修改
        """
        self.status = self.OPEN
        self.save()
    thaw.alters_data = True

    # submit 提交
    def submit(self):
        """
        Mark this basket as submitted
        标记这个购物篮并提交
        """
        self.status = self.SUBMITTED
        self.date_submitted = now()
        self.save()
    submit.alters_data = True

    # Kept for backwards compatibility
    # 保持向后兼容
    set_as_submitted = submit

    # 是否需要运输
    def is_shipping_required(self):
        """
        Test whether the basket contains physical products that require
        shipping.
        测试购物篮里是否包含需要运输的物理产品。
        """
        for line in self.all_lines():
            if line.product.is_shipping_required:
                return True
        return False

    # =======
    # Helpers 助手
    # =======

    # 创建一个引用
    def _create_line_reference(self, product, stockrecord, options):
        """
        Returns a reference string for a line based on the item
        and its options.
        返回基于项目及其选项的行的引用字符串。
        """
        base = '%s_%s' % (product.id, stockrecord.id)
        if not options:
            return base
        repr_options = [{'option': repr(option['option']),
                         'value': repr(option['value'])} for option in options]
        return "%s_%s" % (base, zlib.crc32(repr(repr_options).encode('utf8')))

    # 获取总数
    def _get_total(self, property):
        """
        For executing a named method on each line of the basket
        and returning the total.
        用于在购物篮的每一行上执行命名方法并返回总数。
        """
        total = D('0.00')
        for line in self.all_lines():
            try:
                total += getattr(line, property)
            except ObjectDoesNotExist:
                # Handle situation where the product may have been deleted
                # 处理产品可能已被删除的情况
                pass
            except TypeError:
                # Handle Unavailable products with no known price
                # 处理不知道价格的不可用产品
                info = self.get_stock_info(line.product, line.attributes.all())
                if info.availability.is_available_to_buy:
                    raise
                pass
        return total

    # ==========
    # Properties 特性
    # ==========

    @property
    def is_empty(self):
        """
        Test if this basket is empty
        测试这个购物篮是否是空的
        """
        return self.id is None or self.num_lines == 0

    @property
    def is_tax_known(self):
        """
        Test if tax values are known for this basket
        测试这个购物篮是否已知税收值
        """
        return all([line.is_tax_known for line in self.all_lines()])

    @property
    def total_excl_tax(self):
        """
        Return total line price excluding tax
        返回总价不含税
        """
        return self._get_total('line_price_excl_tax_incl_discounts')

    @property
    def total_tax(self):
        """
            Return total tax for a line
            返回一条行的总税
        """
        return self._get_total('line_tax')

    @property
    def total_incl_tax(self):
        """
        Return total price inclusive of tax and discounts
        包括税收和折扣在内的总价格
        """
        return self._get_total('line_price_incl_tax_incl_discounts')

    @property
    def total_incl_tax_excl_discounts(self):
        """
        Return total price inclusive of tax but exclusive discounts
        返回总价格，包括税收，但独家折扣
        """
        return self._get_total('line_price_incl_tax')

    @property
    def total_discount(self):       # 总折扣
        return self._get_total('discount_value')

    @property
    def offer_discounts(self):  # 折扣优惠
        """
        Return basket discounts from non-voucher sources.  Does not include
        shipping discounts.

        从非凭证来源返回购物篮折扣。不包括运输折扣。
        """
        return self.offer_applications.offer_discounts

    @property
    def voucher_discounts(self):    # 凭单折扣
        """
        Return discounts from vouchers
        从凭证中退回折扣
        """
        return self.offer_applications.voucher_discounts

    @property
    def has_shipping_discounts(self):       # 判断是否有运输折扣？
        return len(self.shipping_discounts) > 0

    @property
    def shipping_discounts(self):    # 运输折扣
        """
        Return discounts from vouchers
        从凭证中退回折扣
        """
        return self.offer_applications.shipping_discounts

    @property
    def post_order_actions(self):   # 订单后行动
        """
        Return discounts from vouchers
        从凭证中退回折扣
        """
        return self.offer_applications.post_order_actions

    @property
    def grouped_voucher_discounts(self):    # 按发票金额折扣
        """
        Return discounts from vouchers but grouped so that a voucher which
        links to multiple offers is aggregated into one object.
        从凭证中返回折扣，但分组，以便将链接到多个优惠的凭证汇总为一个对象。
        """
        return self.offer_applications.grouped_voucher_discounts

    @property
    def total_excl_tax_excl_discounts(self):    # 总免税额折扣
        """
        Return total price excluding tax and discounts
        扣除税金和折扣后的总价格
        """
        return self._get_total('line_price_excl_tax')

    @property
    def num_lines(self):
        """
        Return number of lines
        返回行数
        """
        return self.all_lines().count()

    @property
    def num_items(self):
        """
        Return number of items
        返回项目数
        """
        return sum(line.quantity for line in self.lines.all())

    @property
    def num_items_without_discount(self):   # 无折扣项目
        num = 0
        for line in self.all_lines():
            num += line.quantity_without_discount
        return num

    @property
    def num_items_with_discount(self):  # 优惠折扣
        num = 0
        for line in self.all_lines():
            num += line.quantity_with_discount
        return num

    @property
    def time_before_submit(self):   # 提交前
        if not self.date_submitted:
            return None
        return self.date_submitted - self.date_created

    @property
    def time_since_creation(self, test_datetime=None):  # 创建以来的时间
        if not test_datetime:
            test_datetime = now()
        return test_datetime - self.date_created

    @property
    def contains_a_voucher(self):   # 包含凭证
        if not self.id:
            return False
        return self.vouchers.exists()

    @property
    def is_submitted(self):     # 提交后
        return self.status == self.SUBMITTED

    @property
    def can_be_edited(self):    # 可以编辑
        """
        Test if a basket can be edited
        测试购物篮是否可以编辑
        """
        return self.status in self.editable_statuses

    @property
    def currency(self):     # 货币
        # Since all lines should have the same currency, return the currency of
        # the first one found.
        # 因为所有的行都应该有相同的货币，返回第一个找到的货币。
        for line in self.all_lines():
            return line.price_currency

    # =============
    # Query methods 查询方法
    # =============

    # 收货人凭单
    def contains_voucher(self, code):
        """
        Test whether the basket contains a voucher with a given code
        测试购物篮是否包含有给定代码的凭证
        """
        if self.id is None:
            return False
        try:
            self.vouchers.get(code=code)
        except ObjectDoesNotExist:
            return False
        else:
            return True

    def product_quantity(self, product):    # 产品数量
        """
        Return the quantity of a product in the basket

        The basket can contain multiple lines with the same product, but
        different options and stockrecords. Those quantities are summed up.

        退回购物篮里的产品数量
        购物篮可以包含同一产品的多条线，但是不同的选择和库存记录。这些量是相加的。

        """
        matching_lines = self.lines.filter(product=product)
        quantity = matching_lines.aggregate(Sum('quantity'))['quantity__sum']
        return quantity or 0

    # 行 数量 （self, 产品，库存记录，选项 关）
    def line_quantity(self, product, stockrecord, options=None):
        """
        Return the current quantity of a specific product and options
        返回特定产品和选项的当前数量
        """
        ref = self._create_line_reference(product, stockrecord, options)
        try:
            return self.lines.get(line_reference=ref).quantity
        except ObjectDoesNotExist:
            return 0


# 抽象 行 （生成行 类)
class AbstractLine(models.Model):
    """A line of a basket (product and a quantity)

    Common approaches on ordering basket lines:

        a) First added at top. That's the history-like approach; new items are
           added to the bottom of the list. Changing quantities doesn't impact
           position.
           Oscar does this by default. It just sorts by Line.pk, which is
           guaranteed to increment after each creation.

        b) Last modified at top. That means items move to the top when you add
           another one, and new items are added to the top as well.  Amazon
           mostly does this, but doesn't change the position when you update
           the quantity in the basket view.
           To get this behaviour, add a date_updated field, change
           Meta.ordering and optionally do something similar on wishlist lines.
           Order lines should already be created in the order of the basket
           lines, and are sorted by their primary key, so no changes should be
           necessary there.

    购物篮（产品和数量）
    订购购物篮行的常用方法：
        a)首先添加在顶部。这是历史的方法；新项目是添加到列表的底部。变化数量不影响位置。
            奥斯卡默认是这样做的。它只是按线性排序。保证每次创建后增量。
        b)最后在顶部修改。这意味着当添加时，项目会移到顶部。另一个，新项目也被添加到顶部。
        亚马逊主要是这样做，但是在更新时不会改变位置，购物篮里的数量。
        为了获得这种行为，添加一个DATEX更新的字段，更改Meta.ordering 可选地按愿望线做类似的事情。
        命令行应该已经按照购物篮行的顺序创建了，并且按它们的主键排序，因此在那里不需要进行任何更改。
    """
    basket = models.ForeignKey(
        'basket.Basket',
        on_delete=models.CASCADE,
        related_name='lines',
        verbose_name=_("Basket"))

    # This is to determine which products belong to the same line
    # We can't just use product.id as you can have customised products
    # which should be treated as separate lines.  Set as a
    # SlugField as it is included in the path for certain views.
    # 这是为了确定哪些产品属于同一行。
    # 我们不能只使用产品ID，你也可以定制产品而且设为分开的行。
    # 可以像SlugField那样去设置，包含在某些视图的路径中。

    line_reference = SlugField(
        _("Line Reference"), max_length=128, db_index=True)

    product = models.ForeignKey(
        'catalogue.Product',
        on_delete=models.CASCADE,
        related_name='basket_lines',
        verbose_name=_("Product"))

    # We store the stockrecord that should be used to fulfil this line.
    # 我们存储应该用来实现这条行的库存记录。
    stockrecord = models.ForeignKey(
        'partner.StockRecord',
        on_delete=models.CASCADE,
        related_name='basket_lines')

    quantity = models.PositiveIntegerField(_('Quantity'), default=1)

    # We store the unit price incl tax of the product when it is first added to
    # the basket.  This allows us to tell if a product has changed price since
    # a person first added it to their basket.
    # 我们在第一次添加到购物篮中时存储产品的单位价格税。这使我们能够知道产品是否
    # 已经改变价格，因为一个人首先把它添加到他们的篮子里。
    price_currency = models.CharField(
        _("Currency"), max_length=12, default=get_default_currency)
    price_excl_tax = models.DecimalField(
        _('Price excl. Tax'), decimal_places=2, max_digits=12,
        null=True)
    price_incl_tax = models.DecimalField(
        _('Price incl. Tax'), decimal_places=2, max_digits=12, null=True)

    # Track date of first addition
    # 第一次追加日期
    date_created = models.DateTimeField(_("Date Created"), auto_now_add=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Instance variables used to persist discount information
        # 用于保存折扣信息的实例变量
        self._discount_excl_tax = D('0.00')
        self._discount_incl_tax = D('0.00')
        self.consumer = LineOfferConsumer(self)

    class Meta:
        abstract = True
        app_label = 'basket'
        # Enforce sorting by order of creation.
        # 按创建顺序执行排序。
        ordering = ['date_created', 'pk']
        unique_together = ("basket", "line_reference")
        verbose_name = _('Basket line')
        verbose_name_plural = _('Basket lines')

    def __str__(self):
        return _(
            "Basket #%(basket_id)d, Product #%(product_id)d, quantity"
            " %(quantity)d") % {'basket_id': self.basket.pk,
                                'product_id': self.product.pk,
                                'quantity': self.quantity}

    def save(self, *args, **kwargs):
        if not self.basket.can_be_edited:
            raise PermissionDenied(
                _("You cannot modify a %s basket") % (
                    self.basket.status.lower(),))
        return super().save(*args, **kwargs)

    # =============
    # Offer methods 要约方法
    # =============

    def clear_discount(self):   # 清除折扣
        """
        Remove any discounts from this line.
        从这一行删除任何折扣。
        """
        self._discount_excl_tax = D('0.00')
        self._discount_incl_tax = D('0.00')
        self.consumer = LineOfferConsumer(self)

    def discount(self, discount_value, affected_quantity, incl_tax=True,
                 offer=None):
        """
        Apply a discount to this line
        对这行打折扣
        """
        if incl_tax:
            if self._discount_excl_tax > 0:
                # 在已申请税收优惠折扣时，尝试折价一条行的含税价格
                raise RuntimeError(
                    "Attempting to discount the tax-inclusive price of a line "
                    "when tax-exclusive discounts are already applied")
            self._discount_incl_tax += discount_value
        else:
            if self._discount_incl_tax > 0:
                # 在扣除税收优惠的情况下，尝试打折一个专线的排税价格
                raise RuntimeError(
                    "Attempting to discount the tax-exclusive price of a line "
                    "when tax-inclusive discounts are already applied")
            self._discount_excl_tax += discount_value
        self.consume(affected_quantity, offer=offer)

    # consume消费
    def consume(self, quantity, offer=None):
        """
        Mark all or part of the line as 'consumed'

        Consumed items are no longer available to be used in offers.

        将所有或部分行标记为“消耗” 消费品不再可用于要约
        """
        self.consumer.consume(quantity, offer=offer)

    # 价格故障
    def get_price_breakdown(self):
        """
        Return a breakdown of line prices after discounts have been applied.

        Returns a list of (unit_price_incl_tax, unit_price_excl_tax, quantity)
        tuples.

        在打折后，返回行路价格的细分。返回一个列表（单价税, 单价免税,数量）元组。
        """
        if not self.is_tax_known:
            # 价格故障只能在税收已知时确定。
            raise RuntimeError("A price breakdown can only be determined "
                               "when taxes are known")
        prices = []
        if not self.discount_value:
            prices.append((self.unit_price_incl_tax, self.unit_price_excl_tax,
                           self.quantity))
        else:
            # Need to split the discount among the affected quantity
            # of products.
            # 影响产品数量的折扣
            item_incl_tax_discount = (
                self.discount_value / int(self.consumer.consumed()))
            item_excl_tax_discount = item_incl_tax_discount * self._tax_ratio
            item_excl_tax_discount = item_excl_tax_discount.quantize(D('0.01'))
            prices.append((self.unit_price_incl_tax - item_incl_tax_discount,
                           self.unit_price_excl_tax - item_excl_tax_discount,
                           self.consumer.consumed()))
            if self.quantity_without_discount:
                prices.append((self.unit_price_incl_tax,
                               self.unit_price_excl_tax,
                               self.quantity_without_discount))
        return prices

    # =======
    # Helpers   助手
    # =======

    @property
    def _tax_ratio(self):       # 税收比率
        if not self.unit_price_incl_tax:
            return 0
        return self.unit_price_excl_tax / self.unit_price_incl_tax

    # ===============
    # Offer Discounts  要约折扣
    # ===============

    def has_offer_discount(self, offer):    # 是否有要约折扣
        return self.consumer.consumed(offer) > 0

    def quantity_with_offer_discount(self, offer):      # 要约打折数量
        return self.consumer.consumed(offer)

    def quantity_without_offer_discount(self, offer):       # 无要约折扣数量
        return self.consumer.available(offer)

    def is_available_for_offer_discount(self, offer):       # 可用要约折扣
        return self.consumer.available(offer) > 0

    # ==========
    # Properties 特性
    # ==========

    @property
    def has_discount(self):     # 是否有折扣
        return bool(self.consumer.consumed())

    @property
    def quantity_with_discount(self):   # 折扣数量
        return self.consumer.consumed()

    @property
    def quantity_without_discount(self):    # 无折扣数量
        return self.consumer.available()

    @property
    def is_available_for_discount(self):    # 可用折扣
        # deprecated
        return self.consumer.available() > 0

    @property
    def discount_value(self):   # 折扣价值
        # Only one of the incl- and excl- discounts should be non-zero
        # 只有一个进出口折扣应该是非零的。
        return max(self._discount_incl_tax, self._discount_excl_tax)

    @property
    def purchase_info(self):        # 采购信息
        """
        Return the stock/price info
        返回库存/价格信息
        """
        if not hasattr(self, '_info'):
            # Cache the PurchaseInfo instance.
            # 缓存购买信息实例。
            self._info = self.basket.strategy.fetch_for_line(
                self, self.stockrecord)
        return self._info

    @property
    def is_tax_known(self):     # 税收是已知的
        return self.purchase_info.price.is_tax_known

    @property
    def unit_effective_price(self):     # 单位有效价格
        """
        The price to use for offer calculations
        报价计算的使用价格
        """
        return self.purchase_info.price.effective_price

    @property
    def unit_price_excl_tax(self):      # 单价免税
        return self.purchase_info.price.excl_tax

    @property
    def unit_price_incl_tax(self):      # 单价税
        return self.purchase_info.price.incl_tax

    @property
    def unit_tax(self):     # 单位税
        return self.purchase_info.price.tax

    @property
    def line_price_excl_tax(self):  # 折价税
        if self.unit_price_excl_tax is not None:
            return self.quantity * self.unit_price_excl_tax

    @property
    def line_price_excl_tax_incl_discounts(self): # 除税后的价格
        if self._discount_excl_tax and self.line_price_excl_tax is not None:
            return self.line_price_excl_tax - self._discount_excl_tax
        if self._discount_incl_tax and self.line_price_incl_tax is not None:
            # This is a tricky situation.  We know the discount as calculated
            # against tax inclusive prices but we need to guess how much of the
            # discount applies to tax-exclusive prices.  We do this by
            # assuming a linear tax and scaling down the original discount.

            # 这是一个棘手的情况。我们知道按含税价格计算的折扣，但我们需要猜出多少折扣
            # 适用于免税价格。我们这样做是假设线性税收和缩小原来的折扣。
            return self.line_price_excl_tax \
                - self._tax_ratio * self._discount_incl_tax
        return self.line_price_excl_tax

    @property
    def line_price_incl_tax_incl_discounts(self):       # 线价开征税后折扣
        # We use whichever discount value is set.  If the discount value was
        # calculated against the tax-exclusive prices, then the line price
        # including tax
        # 我们使用哪一个折扣值被设置。如果按免税价格计算折扣值，则包括税收在内的价格
        if self.line_price_incl_tax is not None:
            return self.line_price_incl_tax - self.discount_value

    @property
    def line_tax(self):     # 行税
        if self.is_tax_known:
            return self.quantity * self.unit_tax

    @property
    def line_price_incl_tax(self): # 行价税
        if self.unit_price_incl_tax is not None:
            return self.quantity * self.unit_price_incl_tax

    @property
    def description(self):  # 描述 ，形容;种类;类型
        d = smart_text(self.product)
        ops = []
        for attribute in self.attributes.all():
            ops.append("%s = '%s'" % (attribute.option.name, attribute.value))
        if ops:
            d = "%s (%s)" % (d, ", ".join(ops))
        return d

    def get_warning(self):      # 获取警告
        """
        Return a warning message about this basket line if one is applicable

        This could be things like the price has changed
        如果一个适用的话，返回一个关于这个购物篮行的警告信息，这可能是价格已经改变的事情。
        """
        if isinstance(self.purchase_info.availability, Unavailable):
            msg = "'%(product)s' is no longer available"
            return _(msg) % {'product': self.product.get_title()}

        if not self.price_incl_tax:
            return
        if not self.purchase_info.price.is_tax_known:
            return

        # Compare current price to price when added to basket
        # 把当前价格和加在购物篮里的价格比较一下
        current_price_incl_tax = self.purchase_info.price.incl_tax
        if current_price_incl_tax != self.price_incl_tax:
            product_prices = {
                'product': self.product.get_title(),
                'old_price': currency(self.price_incl_tax),
                'new_price': currency(current_price_incl_tax)
            }
            if current_price_incl_tax > self.price_incl_tax:
                # 自从你把它加到你的购物篮里以后，产品的价格就从老的价格上升到新的价格。
                warning = _("The price of '%(product)s' has increased from"
                            " %(old_price)s to %(new_price)s since you added"
                            " it to your basket")
                return warning % product_prices
            else:
                # 因为你把它加到你的购物篮里，所以产品的价格已经从老的价格降到了新的价格
                warning = _("The price of '%(product)s' has decreased from"
                            " %(old_price)s to %(new_price)s since you added"
                            " it to your basket")
                return warning % product_prices


# 抽象行属性 （生成行属性类）
class AbstractLineAttribute(models.Model):
    """
    An attribute of a basket line
    购物篮行的属性
    """
    line = models.ForeignKey(
        'basket.Line',
        on_delete=models.CASCADE,
        related_name='attributes',
        verbose_name=_("Line"))
    option = models.ForeignKey(
        'catalogue.Option',
        on_delete=models.CASCADE,
        verbose_name=_("Option"))
    value = models.CharField(_("Value"), max_length=255)

    class Meta:
        abstract = True
        app_label = 'basket'
        verbose_name = _('Line attribute')
        verbose_name_plural = _('Line attributes')
