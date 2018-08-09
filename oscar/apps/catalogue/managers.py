from django.db import models
from django.db.models import Count


# 产品查询集
class ProductQuerySet(models.query.QuerySet):

    # 基本查询集
    def base_queryset(self):
        """
        Applies select_related and prefetch_related for commonly related
        models to save on queries

        对常用相关模型应用select_related和prefetch_related以保存查询
        """
        return self.select_related('product_class')\
            .prefetch_related('children', 'product_options', 'product_class__options', 'stockrecords', 'images') \
            .annotate(num_product_class_options=Count('product_class__options'),
                      num_product_options=Count('product_options'))

    # 可浏览
    def browsable(self):
        """
        Excludes non-canonical products.
        不包括非规范产品。
        """
        return self.filter(parent=None)


# 产品经理
class ProductManager(models.Manager):
    """
    Uses ProductQuerySet and proxies its methods to allow chaining

    Once Django 1.7 lands, this class can probably be removed:
    https://docs.djangoproject.com/en/dev/releases/1.7/#calling-custom-queryset-methods-from-the-manager  # noqa

    使用ProductQuerySet并代理其方法以允许链接
    一旦Django 1.7登陆，这个类可能会被删除：

    """

    # 获取查询集
    def get_queryset(self):
        return ProductQuerySet(self.model, using=self._db)

    # 可浏览
    def browsable(self):
        return self.get_queryset().browsable()

    # 基本查询集
    def base_queryset(self):
        return self.get_queryset().base_queryset()


# 可浏览产品经理
class BrowsableProductManager(ProductManager):
    """
    Excludes non-canonical products

    Could be deprecated after Oscar 0.7 is released
    不包括非规范产品
    在Oscar 0.7发布后可以弃用
    """

    def get_queryset(self):
        return super().get_queryset().browsable()
