from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _

from oscar.core.compat import AUTH_USER_MODEL


# 抽象产品记录(生成产品记录类)
class AbstractProductRecord(models.Model):
    """
    A record of a how popular a product is.

    This used be auto-merchandising to display the most popular
    products.

    一个产品有多受欢迎的记录。
    自动显示最流行的产品。
    """

    product = models.OneToOneField(
        'catalogue.Product', verbose_name=_("Product"),
        related_name='stats', on_delete=models.CASCADE)

    # Data used for generating a score
    # 用于生成分数的数据

    # 数字视图
    num_views = models.PositiveIntegerField(_('Views'), default=0)
    # 添加到购物篮
    num_basket_additions = models.PositiveIntegerField(
        _('Basket Additions'), default=0)
    # 购买数量
    num_purchases = models.PositiveIntegerField(
        _('Purchases'), default=0, db_index=True)

    # Product score - used within search
    # 产品评分-在搜索中使用
    score = models.FloatField(_('Score'), default=0.00)

    class Meta:
        abstract = True         # 抽象
        app_label = 'analytics'     # app标签 =  'analytics' 分析
        ordering = ['-num_purchases']
        verbose_name = _('Product record')  # verbose 冗长，啰嗦
        verbose_name_plural = _('Product records')

    def __str__(self):
        return _("Record for '%s'") % self.product


# 抽象用户记录(生成用户记录类）
class AbstractUserRecord(models.Model):
    """
    A record of a user's activity.
    用户活动的记录
    """

    user = models.OneToOneField(AUTH_USER_MODEL, verbose_name=_("User"),
                                on_delete=models.CASCADE)

    # Browsing stats
    # 浏览统计

    # 数字产品视图
    num_product_views = models.PositiveIntegerField(
        _('Product Views'), default=0)
    # 添加到购物篮
    num_basket_additions = models.PositiveIntegerField(
        _('Basket Additions'), default=0)

    # Order stats
    # 订单统计

    # 命令
    num_orders = models.PositiveIntegerField(
        _('Orders'), default=0, db_index=True)
    # 命令行
    num_order_lines = models.PositiveIntegerField(
        _('Order Lines'), default=0, db_index=True)
    # 订单项目
    num_order_items = models.PositiveIntegerField(
        _('Order Items'), default=0, db_index=True)
    # 总耗用量
    total_spent = models.DecimalField(_('Total Spent'), decimal_places=2,
                                      max_digits=12, default=Decimal('0.00'))
    # 最后订单日期
    date_last_order = models.DateTimeField(
        _('Last Order Date'), blank=True, null=True)

    class Meta:
        abstract = True
        app_label = 'analytics'
        verbose_name = _('User record')
        verbose_name_plural = _('User records')


# 抽象用户产品视图（生成用户产品视图类)
class AbstractUserProductView(models.Model):

    user = models.ForeignKey(
        AUTH_USER_MODEL, verbose_name=_("User"),
        on_delete=models.CASCADE)
    product = models.ForeignKey(
        'catalogue.Product',
        on_delete=models.CASCADE,
        verbose_name=_("Product"))
    date_created = models.DateTimeField(_("Date Created"), auto_now_add=True)

    class Meta:
        abstract = True
        app_label = 'analytics'
        verbose_name = _('User product view')
        verbose_name_plural = _('User product views')

    def __str__(self):
        return _("%(user)s viewed '%(product)s'") % {
            'user': self.user, 'product': self.product}


# 抽象用户搜索
class AbstractUserSearch(models.Model):

    user = models.ForeignKey(
        AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        verbose_name=_("User"))
    # 查询
    query = models.CharField(_("Search term"), max_length=255, db_index=True)
    date_created = models.DateTimeField(_("Date Created"), auto_now_add=True)

    class Meta:
        abstract = True
        app_label = 'analytics'
        verbose_name = _("User search query")
        verbose_name_plural = _("User search queries")

    def __str__(self):
        return _("%(user)s searched for '%(query)s'") % {
            'user': self.user,
            'query': self.query}
