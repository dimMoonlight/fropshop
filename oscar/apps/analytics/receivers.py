import logging

from django.db import IntegrityError
from django.db.models import F
from django.dispatch import receiver

from oscar.apps.basket.signals import basket_addition
from oscar.apps.catalogue.signals import product_viewed
from oscar.apps.order.signals import order_placed
from oscar.apps.search.signals import user_search
from oscar.core.loading import get_classes

# 用户搜索、用户记录、产品记录、用户产品视图
UserSearch, UserRecord, ProductRecord, UserProductView = get_classes(
    'analytics.models', ['UserSearch', 'UserRecord', 'ProductRecord',
                         'UserProductView'])

# Helpers 助手

# 记录器
logger = logging.getLogger('oscar.analytics')


# 更新计数器
def _update_counter(model, field_name, filter_kwargs, increment=1):
    """
    Efficiently updates a counter field by a given increment. Uses Django's
    update() call to fetch and update in one query.

    TODO: This has a race condition, we should use UPSERT here

    :param model: The model class of the recording model
    :param field_name: The name of the field to update
    :param filter_kwargs: Parameters to the ORM's filter() function to get the
                          correct instance

     通过给定增量有效地更新计数器字段。使用Django的Update（）调用在一个查询中获取和更新。
     Todo:这有一个资源竞争，我们应该在这里使用 UPSERT
    参数：模型：参数模型类的记录
    参数：字段名称：要更新的字段的名称
    参数：过滤器_关键字参数：参数到 函数 ORM's filter()以获得正确的实例
    """
    try:
        # 记录
        record = model.objects.filter(**filter_kwargs)
        # 影响
        affected = record.update(**{field_name: F(field_name) + increment})
        if not affected:
            filter_kwargs[field_name] = increment
            model.objects.create(**filter_kwargs)
    # 完整性误差
    except IntegrityError:      # pragma: no cover 杂注：没有被覆盖
        # get_or_create has a race condition (we should use upsert in supported)
        # databases. For now just ignore these errors
        # 获取或创建有一个资源竞争（我们应该在支持中使用UpSert）
        # 数据库。现在就忽略这些错误

        #记录器错误
        logger.error(
            "IntegrityError when updating analytics counter for %s", model)


# 按顺序记录产品
def _record_products_in_order(order):
    # surely there's a way to do this without causing a query for each line?
    # 当然，有一种方法可以做到这一点而不引起对每一行的查询吗？
    for line in order.lines.all():
        _update_counter(
            ProductRecord, 'num_purchases',
            {'product': line.product}, line.quantity)


# 记录用户订单
def _record_user_order(user, order):
    try:
        record = UserRecord.objects.filter(user=user)
        affected = record.update(
            num_orders=F('num_orders') + 1,
            num_order_lines=F('num_order_lines') + order.num_lines,
            num_order_items=F('num_order_items') + order.num_items,
            total_spent=F('total_spent') + order.total_incl_tax,
            date_last_order=order.date_placed)
        if not affected:
            UserRecord.objects.create(
                user=user, num_orders=1, num_order_lines=order.num_lines,
                num_order_items=order.num_items,
                total_spent=order.total_incl_tax,
                date_last_order=order.date_placed)
    except IntegrityError:      # pragma: no cover
        logger.error(
            "IntegrityError in analytics when recording a user order.")


# Receivers 接收机

@receiver(product_viewed)
# 接收产品视图
def receive_product_view(sender, product, user, **kwargs):
    if kwargs.get('raw', False):
        return
    _update_counter(ProductRecord, 'num_views', {'product': product})
    if user and user.is_authenticated:
        _update_counter(UserRecord, 'num_product_views', {'user': user})
        UserProductView.objects.create(product=product, user=user)


@receiver(user_search)
# 接收产品搜索
def receive_product_search(sender, query, user, **kwargs):
    if user and user.is_authenticated and not kwargs.get('raw', False):
        UserSearch._default_manager.create(user=user, query=query)


@receiver(basket_addition)
# 接收附件栏
def receive_basket_addition(sender, product, user, **kwargs):
    if kwargs.get('raw', False):
        return
    _update_counter(
        ProductRecord, 'num_basket_additions', {'product': product})
    if user and user.is_authenticated:
        _update_counter(UserRecord, 'num_basket_additions', {'user': user})


@receiver(order_placed)
#  接收订单
def receive_order_placed(sender, order, user, **kwargs):
    if kwargs.get('raw', False):
        return
    _record_products_in_order(order)
    if user and user.is_authenticated:
        _record_user_order(user, order)
