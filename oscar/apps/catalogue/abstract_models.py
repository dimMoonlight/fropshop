import logging
import os
from datetime import date, datetime

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib.staticfiles.finders import find
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.files.base import File
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Count, Sum
from django.urls import reverse
from django.utils.functional import cached_property
from django.utils.html import strip_tags
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from django.utils.translation import get_language, pgettext_lazy
from treebeard.mp_tree import MP_Node

from oscar.core.loading import get_class, get_classes, get_model
from oscar.core.utils import slugify
from oscar.core.validators import non_python_keyword
from oscar.models.fields import AutoSlugField, NullCharField
from oscar.models.fields.slugfield import SlugField

# 产品管理，可浏览产品管理
ProductManager, BrowsableProductManager = get_classes(
    'catalogue.managers', ['ProductManager', 'BrowsableProductManager'])
# 产品属性容器
ProductAttributesContainer = get_class(
    'catalogue.product_attributes', 'ProductAttributesContainer')
# 选择器
Selector = get_class('partner.strategy', 'Selector')


# 抽象产品类
class AbstractProductClass(models.Model):
    """
    Used for defining options and attributes for a subset of products.
    E.g. Books, DVDs and Toys. A product can only belong to one product class.

    At least one product class must be created when setting up a new
    Oscar deployment.

    Not necessarily equivalent to top-level categories but usually will be.


    用于定义产品子集的选项和属性。
    例如书籍、DVD和玩具。产品只能属于一个产品类
    在建立新的奥斯卡部署时，必须创建至少一个产品类。
    不一定等同于顶级类别，但通常是等价的。
    """
    name = models.CharField(_('Name'), max_length=128)
    slug = AutoSlugField(_('Slug'), max_length=128, unique=True,
                         populate_from='name')

    #: Some product type don't require shipping (eg digital products) - we use
    #: this field to take some shortcuts in the checkout.
    # 一些产品类型不需要运输（如数字产品）-我们使用这一领域采取一些快捷方式在结帐。
    requires_shipping = models.BooleanField(_("Requires shipping?"),
                                            default=True)

    #: Digital products generally don't require their stock levels to be
    #: tracked.
    # 数字产品一般不需要跟踪他们的库存水平。
    track_stock = models.BooleanField(_("Track stock levels?"), default=True)

    #: These are the options (set by the user when they add to basket) for this
    #: item class.  For instance, a product class of "SMS message" would always
    #: require a message to be specified before it could be bought.
    #: Note that you can also set options on a per-product level.
    # 这些选项（由用户在添加到购物篮中时）为该项类设置。例如，“SMS消息”的产品类别总是
    # 需要在购买之前指定一条消息。注意，您也可以在每个产品级别上设置选项。
    options = models.ManyToManyField(
        'catalogue.Option', blank=True, verbose_name=_("Options"))

    class Meta:
        abstract = True
        app_label = 'catalogue'
        ordering = ['name']
        verbose_name = _("Product class")
        verbose_name_plural = _("Product classes")

    def __str__(self):
        return self.name

    @property
    def has_attributes(self):
        return self.attributes.exists()


# 抽象 类型，类别(生成类别，类目 类)
class AbstractCategory(MP_Node):
    """
    A product category. Merely used for navigational purposes; has no
    effects on business logic.

    Uses django-treebeard.

    产品类别。仅用于导航目的；对业务逻辑没有影响。
    使用 django-treebeard.
    """
    name = models.CharField(_('Name'), max_length=255, db_index=True)
    description = models.TextField(_('Description'), blank=True)
    image = models.ImageField(_('Image'), upload_to='categories', blank=True,
                              null=True, max_length=255)
    slug = SlugField(_('Slug'), max_length=255, db_index=True)

    _slug_separator = '/'
    _full_name_separator = ' > '

    def __str__(self):
        return self.full_name

    @property
    def full_name(self):
        """
        Returns a string representation of the category and it's ancestors,
        e.g. 'Books > Non-fiction > Essential programming'.

        It's rarely used in Oscar's codebase, but used to be stored as a
        CharField and is hence kept for backwards compatibility. It's also
        sufficiently useful to keep around.

        返回类别的字符串表示形式及其祖先，例如“书籍>非小说>基本程序”。
        它很少在奥斯卡的代码库中使用，但通常被存储为CharField因此被保持向后兼容。
        它也是足够有用以保持周围。
        """
        names = [category.name for category in self.get_ancestors_and_self()]
        return self._full_name_separator.join(names)

    @property
    def full_slug(self):
        """
        Returns a string of this category's slug concatenated with the slugs
        of it's ancestors, e.g. 'books/non-fiction/essential-programming'.

        Oscar used to store this as in the 'slug' model field, but this field
        has been re-purposed to only store this category's slug and to not
        include it's ancestors' slugs.

        返回这个类别的字符串与它原型的slug的字符串，例如“书籍/非小说/本质编程”。
        奥斯卡曾经把它存储在“slug”模型领域，但是这个领域已重新打算只存储这类的
        slug和不包括祖先的slug。
        """
        slugs = [category.slug for category in self.get_ancestors_and_self()]
        return self._slug_separator.join(slugs)

    # 生成slug
    def generate_slug(self):
        """
        Generates a slug for a category. This makes no attempt at generating
        a unique slug.

        生成一个类别的slug。这并没有试图产生一个独特的slug。
        """
        return slugify(self.name)

    # 确保slug的唯一性
    def ensure_slug_uniqueness(self):
        """
        Ensures that the category's slug is unique amongst it's siblings.
        This is inefficient and probably not thread-safe.

        确保类别的slug在它的兄弟姐妹中是独一无二的。这是低效的，线程安全也可能出问题
        """
        unique_slug = self.slug
        siblings = self.get_siblings().exclude(pk=self.pk)
        next_num = 2
        while siblings.filter(slug=unique_slug).exists():
            unique_slug = '{slug}_{end}'.format(slug=self.slug, end=next_num)
            next_num += 1

        if unique_slug != self.slug:
            self.slug = unique_slug
            self.save()

    def save(self, *args, **kwargs):
        """
        Oscar traditionally auto-generated slugs from names. As that is
        often convenient, we still do so if a slug is not supplied through
        other means. If you want to control slug creation, just create
        instances with a slug already set, or expose a field on the
        appropriate forms.

        奥斯卡传统上从名字自动生成slug。因为这通常是方便的，我们仍然这样做，如果slug
        不通过其他方式提供。如果你想控制slug的创建，只需创建已经设置了slug的实例，
        或者在适当的窗体上公开一个字段。
        """
        if self.slug:
            # Slug was supplied. Hands off!
            super().save(*args, **kwargs)
        else:
            self.slug = self.generate_slug()
            super().save(*args, **kwargs)
            # We auto-generated a slug, so we need to make sure that it's
            # unique. As we need to be able to inspect the category's siblings
            # for that, we need to wait until the instance is saved. We
            # update the slug and save again if necessary.
            # 我们自动产生一个slug，所以我们需要确保它是独一无二的。由于我们需要能
            # 够检查类别的兄弟姐妹，所以我们需要等到保存实例为止。我们更新slug并保存
            # 如果有必要的话。
            self.ensure_slug_uniqueness()

    # 获得原型和自我
    def get_ancestors_and_self(self):
        """
        Gets ancestors and includes itself. Use treebeard's get_ancestors
        if you don't want to include the category itself. It's a separate
        function as it's commonly used in templates.

        获取原型，包括自己。如果不想包含类别本身，请使用treebeard's get_ancestors。
        它是一个单独的函数，通常在模板中使用。
        """
        return list(self.get_ancestors()) + [self]

    # 获得子类和自我
    def get_descendants_and_self(self):
        """
        Gets descendants and includes itself. Use treebeard's get_descendants
        if you don't want to include the category itself. It's a separate
        function as it's commonly used in templates.

        得到子类，包括自己。如果你不想包括类别本身，请使用treebeard's get_descendants。
        它是一个单独的函数，通常在模板中使用。
        """
        return list(self.get_descendants()) + [self]

    # 获取URL缓存密钥
    def get_url_cache_key(self):
        current_locale = get_language()
        cache_key = 'CATEGORY_URL_%s_%s' % (current_locale, self.pk)
        return cache_key

    # 获取绝对URL
    def get_absolute_url(self):
        """
        Our URL scheme means we have to look up the category's ancestors. As
        that is a bit more expensive, we cache the generated URL. That is
        safe even for a stale cache, as the default implementation of
        ProductCategoryView does the lookup via primary key anyway. But if
        you change that logic, you'll have to reconsider the caching
        approach.

        我们的URL方案意味着我们必须查找类别的原型。因为相对于我们生成的URL更省力。
        即使是默认的ProductCategoryView实现，也可以通过主键进行查找，即使对于过时
        的缓存也是安全的。但是如果你改变了这种逻辑，你就必须重新考虑缓存方法。
        """
        cache_key = self.get_url_cache_key()
        url = cache.get(cache_key)
        if not url:
            url = reverse(
                'catalogue:category',
                kwargs={'category_slug': self.full_slug, 'pk': self.pk})
            cache.set(cache_key, url)
        return url

    class Meta:
        abstract = True
        app_label = 'catalogue'
        ordering = ['path']
        verbose_name = _('Category')
        verbose_name_plural = _('Categories')

    def has_children(self):
        return self.get_num_children() > 0

    def get_num_children(self):
        return self.get_children().count()


# 抽象产品范畴
class AbstractProductCategory(models.Model):
    """
    Joining model between products and categories. Exists to allow customising.
    产品与类别之间的连接模型。存在允许自定义。
    """
    product = models.ForeignKey(
        'catalogue.Product',
        on_delete=models.CASCADE,
        verbose_name=_("Product"))
    category = models.ForeignKey(
        'catalogue.Category',
        on_delete=models.CASCADE,
        verbose_name=_("Category"))

    class Meta:
        abstract = True
        app_label = 'catalogue'
        ordering = ['product', 'category']
        unique_together = ('product', 'category')
        verbose_name = _('Product category')
        verbose_name_plural = _('Product categories')

    def __str__(self):
        return "<productcategory for product '%s'>" % self.product


# 抽象产品
class AbstractProduct(models.Model):
    """
    The base product object

    There's three kinds of products; they're distinguished by the structure
    field.

    - A stand alone product. Regular product that lives by itself.
    - A child product. All child products have a parent product. They're a
      specific version of the parent.
    - A parent product. It essentially represents a set of products.

    An example could be a yoga course, which is a parent product. The different
    times/locations of the courses would be associated with the child products.

    基本产品对象
    有三种产品，它们区别于结构域。
    - 一个独立的产品。正常生活的产品。
    - 子产品 ：所有子产品都有父产品。它们是父产品的特定版本。

    一个例子 ：可以是瑜伽课程，它是父产品。课程的不同时间/地点将与子产品相关。
    """
    STANDALONE, PARENT, CHILD = 'standalone', 'parent', 'child'
    STRUCTURE_CHOICES = (
        (STANDALONE, _('Stand-alone product')),
        (PARENT, _('Parent product')),
        (CHILD, _('Child product'))
    )
    structure = models.CharField(
        _("Product structure"), max_length=10, choices=STRUCTURE_CHOICES,
        default=STANDALONE)

    upc = NullCharField(
        _("UPC"), max_length=64, blank=True, null=True, unique=True,
        help_text=_("Universal Product Code (UPC) is an identifier for "
                    "a product which is not specific to a particular "
                    " supplier. Eg an ISBN for a book."))

    parent = models.ForeignKey(
        'self',
        blank=True,
        null=True,
        on_delete=models.CASCADE,
        related_name='children',
        verbose_name=_("Parent product"),
        help_text=_("Only choose a parent product if you're creating a child "
                    "product.  For example if this is a size "
                    "4 of a particular t-shirt.  Leave blank if this is a "
                    "stand-alone product (i.e. there is only one version of"
                    " this product)."))

    # Title is mandatory for canonical products but optional for child products
    # 标题是强制性的规范产品，除了可选的子产品
    title = models.CharField(pgettext_lazy('Product title', 'Title'),
                             max_length=255, blank=True)
    slug = models.SlugField(_('Slug'), max_length=255, unique=False)
    description = models.TextField(_('Description'), blank=True)

    #: "Kind" of product, e.g. T-Shirt, Book, etc.
    #: None for child products, they inherit their parent's product class
    # 产品的“种类”，例如 T恤，书籍等。没有子产品，他们继承了父产品类别
    product_class = models.ForeignKey(
        'catalogue.ProductClass',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        verbose_name=_('Product type'), related_name="products",
        help_text=_("Choose what type of product this is"))
    attributes = models.ManyToManyField(
        'catalogue.ProductAttribute',
        through='ProductAttributeValue',
        verbose_name=_("Attributes"),
        help_text=_("A product attribute is something that this product may "
                    "have, such as a size, as specified by its class"))
    #: It's possible to have options product class-wide, and per product.
    # 可以在产品类范围和每个产品中选择
    product_options = models.ManyToManyField(
        'catalogue.Option', blank=True, verbose_name=_("Product options"),
        help_text=_("Options are values that can be associated with a item "
                    "when it is added to a customer's basket.  This could be "
                    "something like a personalised message to be printed on "
                    "a T-shirt."))

    # 推荐产品
    recommended_products = models.ManyToManyField(
        'catalogue.Product', through='ProductRecommendation', blank=True,
        verbose_name=_("Recommended products"),
        help_text=_("These are products that are recommended to accompany the "
                    "main product."))

    # Denormalised product rating - used by reviews app.
    # Product has no ratings if rating is None
    # 非规范化产品评级 - 由评论应用程序使用。
    # 如果评分为无，产品没有评分

    # 评分
    rating = models.FloatField(_('Rating'), null=True, editable=False)

    date_created = models.DateTimeField(_("Date created"), auto_now_add=True)

    # This field is used by Haystack to reindex search
    # Haystack使用此字段来重新索引搜索
    date_updated = models.DateTimeField(
        _("Date updated"), auto_now=True, db_index=True)

    # 类别
    categories = models.ManyToManyField(
        'catalogue.Category', through='ProductCategory',
        verbose_name=_("Categories"))

    #: Determines if a product may be used in an offer. It is illegal to
    #: discount some types of product (e.g. ebooks) and this field helps
    #: merchants from avoiding discounting such products
    #: Note that this flag is ignored for child products; they inherit from
    #: the parent product.
    #  确定产品是否可用于要约。 某些类型的折扣产品（例如电子书）是非法的，并且该字段
    #  帮助商家避免这些折扣产品
    # 请注意，子产品会忽略此标志; 他们从父产品继承。

    is_discountable = models.BooleanField(
        _("Is discountable?"), default=True, help_text=_(
            "This flag indicates if this product can be used in an offer "
            "or not"))

    objects = ProductManager()
    browsable = BrowsableProductManager()

    class Meta:
        abstract = True
        app_label = 'catalogue'
        ordering = ['-date_created']
        verbose_name = _('Product')
        verbose_name_plural = _('Products')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.attr = ProductAttributesContainer(product=self)

    def __str__(self):
        if self.title:
            return self.title
        if self.attribute_summary:
            return "%s (%s)" % (self.get_title(), self.attribute_summary)
        else:
            return self.get_title()

    def get_absolute_url(self):
        """
        Return a product's absolute url
        返回产品的绝对网址
        """
        return reverse('catalogue:detail',
                       kwargs={'product_slug': self.slug, 'pk': self.id})

    # 清除
    def clean(self):
        """
        Validate a product. Those are the rules:

        +---------------+-------------+--------------+--------------+
        |               | stand alone | parent       | child        |
        +---------------+-------------+--------------+--------------+
        | title         | required    | required     | optional     |
        +---------------+-------------+--------------+--------------+
        | product class | required    | required     | must be None |
        +---------------+-------------+--------------+--------------+
        | parent        | forbidden   | forbidden    | required     |
        +---------------+-------------+--------------+--------------+
        | stockrecords  | 0 or more   | forbidden    | 0 or more    |
        +---------------+-------------+--------------+--------------+
        | categories    | 1 or more   | 1 or more    | forbidden    |
        +---------------+-------------+--------------+--------------+
        | attributes    | optional    | optional     | optional     |
        +---------------+-------------+--------------+--------------+
        | rec. products | optional    | optional     | unsupported  |
        +---------------+-------------+--------------+--------------+
        | options       | optional    | optional     | forbidden    |
        +---------------+-------------+--------------+--------------+

        Because the validation logic is quite complex, validation is delegated
        to the sub method appropriate for the product's structure.

        验证产品。 这些是规则：
        +---------------+-------------+--------------+--------------+
        |               | 独立        |    父类      |    子类      |
        +---------------+-------------+--------------+--------------+
        | 标题          | 需要        | 需要         | 需要         |
        +---------------+-------------+--------------+--------------+
        | 产品类        | 需要        | 需要         | 必须是没有   |
        +---------------+-------------+--------------+--------------+
        | 产品          | 被禁止      | 被禁止       | 需要         |
        +---------------+-------------+--------------+--------------+
        | 库存记录      | 0 或更多    | 被禁止       | 0 或更多     |
        +---------------+-------------+--------------+--------------+
        | 类别          | 1 或更多    | 1 或更多     | 被禁止       |
        +---------------+-------------+--------------+--------------+
        | 属性          | 可选的      | 可选的        | 可选的     |
        +---------------+-------------+--------------+--------------+
        | REC产品       | 可选的      | 可选的       | 不支持       |
        +---------------+-------------+--------------+--------------+
        | 选项          | 可选的      | 可选的       | 被禁止       |
        +---------------+-------------+--------------+--------------+

        由于验证逻辑非常复杂，因此将验证委托给适合产品结构的子方法。
        """
        getattr(self, '_clean_%s' % self.structure)()
        if not self.is_parent:
            self.attr.validate_attributes()

    def _clean_standalone(self):
        """
        Validates a stand-alone product
        验证独立产品
        """
        if not self.title:
            raise ValidationError(_("Your product must have a title."))
        if not self.product_class:
            raise ValidationError(_("Your product must have a product class."))
        if self.parent_id:
            raise ValidationError(_("Only child products can have a parent."))

    def _clean_child(self):
        """
        Validates a child product
        验证子产品
        """
        if not self.parent_id:
            # 子产品需要父类
            raise ValidationError(_("A child product needs a parent."))
        if self.parent_id and not self.parent.is_parent:
            # 您只能将子产品分配给父产品
            raise ValidationError(
                _("You can only assign child products to parent products."))
        if self.product_class:
            # 子产品不能拥有产品类别
            raise ValidationError(
                _("A child product can't have a product class."))
        if self.pk and self.categories.exists():
            # 子产品不能分配类别
            raise ValidationError(
                _("A child product can't have a category assigned."))
        # Note that we only forbid options on product level
        # 请注意，我们仅禁止产品级别的选项
        if self.pk and self.product_options.exists():
            # 子产品不能有选项。
            raise ValidationError(
                _("A child product can't have options."))

    def _clean_parent(self):
        """
        Validates a parent product.
        验证父产品。
        """
        self._clean_standalone()
        if self.has_stockrecords:
            # 父产品不能有库存记录
            raise ValidationError(
                _("A parent product can't have stockrecords."))

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.get_title())
        super().save(*args, **kwargs)
        self.attr.save()

    # Properties 属性

    @property
    def is_standalone(self):
        return self.structure == self.STANDALONE

    @property
    def is_parent(self):
        return self.structure == self.PARENT

    @property
    def is_child(self):
        return self.structure == self.CHILD

    def can_be_parent(self, give_reason=False):
        """
        Helps decide if a the product can be turned into a parent product.
        帮助确定产品是否可以转换为父产品。
        """
        reason = None
        if self.is_child:
            # 指定的父产品是子产品
            reason = _('The specified parent product is a child product.')
        if self.has_stockrecords:
            # 无法将子产品添加到具有库存记录的产品中
            reason = _(
                "One can't add a child product to a product with stock"
                " records.")
        is_valid = reason is None
        if give_reason:
            return is_valid, reason
        else:
            return is_valid

    @property
    def options(self):
        """
        Returns a set of all valid options for this product.
        It's possible to have options product class-wide, and per product.
        返回此产品的所有有效选项的集合。
        可以在产品类范围和每件产品中选择
        """
        pclass_options = self.get_product_class().options.all()
        return set(pclass_options) or set(self.product_options.all())

    @cached_property
    def has_options(self):
        # Extracting annotated value with number of product class options
        # from product list queryset.
        # 使用产品列表查询集中的产品类选项数提取带注释的值。
        num_product_class_options = getattr(self, 'num_product_class_options', None)
        num_product_options = getattr(self, 'num_product_options', None)
        if num_product_class_options is not None and num_product_options is not None:
            return num_product_class_options > 0 or num_product_options > 0
        return self.get_product_class().options.exists() or self.product_options.exists()

    @property
    def is_shipping_required(self):
        return self.get_product_class().requires_shipping

    @property
    def has_stockrecords(self):
        """
        Test if this product has any stockrecords
        测试该产品是否有任何库存记录
        """
        return self.stockrecords.exists()

    @property
    def num_stockrecords(self):
        return self.stockrecords.count()

    @property
    def attribute_summary(self):
        """
        Return a string of all of a product's attributes
        返回所有产品属性的字符串
        """
        attributes = self.attribute_values.all()
        pairs = [attribute.summary() for attribute in attributes]
        return ", ".join(pairs)

    def get_title(self):
        """
        Return a product's title or it's parent's title if it has no title
        如果没有标题，则返回产品标题或其父类的标题
        """
        title = self.title
        if not title and self.parent_id:
            title = self.parent.title
        return title
    get_title.short_description = pgettext_lazy("Product title", "Title")

    def get_product_class(self):
        """
        Return a product's item class. Child products inherit their parent's.
        返回产品的项目类。 子产品继承其父类产品。
        """
        if self.is_child:
            return self.parent.product_class
        else:
            return self.product_class
    get_product_class.short_description = _("Product class")

    def get_is_discountable(self):
        """
        At the moment, is_discountable can't be set individually for child
        products; they inherit it from their parent.
        目前，不能单独为子产品设置is_discountable，他们必须从父类继承
        """
        if self.is_child:
            return self.parent.is_discountable
        else:
            return self.is_discountable

    # 类别
    def get_categories(self):
        """
        Return a product's categories or parent's if there is a parent product.
        如果有父产品，则退回产品的类别或父类产品。
        """
        if self.is_child:
            return self.parent.categories
        else:
            return self.categories
    get_categories.short_description = _("Categories")

    # Images 图片

    def get_missing_image(self):
        """
        Returns a missing image object.
        返回缺少的图像对象。
        """
        # This class should have a 'name' property so it mimics the Django file
        # field.
        # 这个类应该有一个'name'属性，所以它模仿Django文件字段。
        return MissingProductImage()

    def get_all_images(self):
        if self.is_child and not self.images.exists():
            return self.parent.images.all()
        return self.images.all()

    # 主要形象
    def primary_image(self):
        """
        Returns the primary image for a product. Usually used when one can
        only display one product image, e.g. in a list of products.
        返回产品的主映像。 通常在人们只能显示一个产品图像时使用，例如 在产品列表中。
        """
        images = self.get_all_images()
        ordering = self.images.model.Meta.ordering
        if not ordering or ordering[0] != 'display_order':
            # Only apply order_by() if a custom model doesn't use default
            # ordering. Applying order_by() busts the prefetch cache of
            # the ProductManager
            # 如果自定义模型不使用默认排序，则仅应用order_by（）。 应用order_by（）
            # 会破坏ProductManager的预取高速缓存
            images = images.order_by('display_order')
        try:
            return images[0]
        except IndexError:
            # We return a dict with fields that mirror the key properties of
            # the ProductImage class so this missing image can be used
            # interchangeably in templates.  Strategy pattern ftw!
            # 我们返回一个带有反映ProductImage类的关键属性的字段的字典，因此这个
            # 缺失的图像可以在模板中互换使用。 策略模式ftw！
            return {
                'original': self.get_missing_image(),
                'caption': '',
                'is_missing': True}


    # Updating methods 更新方法
    def update_rating(self):
        """
        Recalculate rating field
        重新计算评级字段
        """
        self.rating = self.calculate_rating()
        self.save()
    update_rating.alters_data = True

    # 计算评级
    def calculate_rating(self):
        """
        Calculate rating value
        计算评级值
        """
        result = self.reviews.filter(
            status=self.reviews.model.APPROVED
        ).aggregate(
            sum=Sum('score'), count=Count('id'))
        reviews_sum = result['sum'] or 0
        reviews_count = result['count'] or 0
        rating = None
        if reviews_count > 0:
            rating = float(reviews_sum) / reviews_count
        return rating

    # 评论
    def has_review_by(self, user):
        if user.is_anonymous:
            return False
        return self.reviews.filter(user=user).exists()

    # 允许审查
    def is_review_permitted(self, user):
        """
        Determines whether a user may add a review on this product.

        Default implementation respects OSCAR_ALLOW_ANON_REVIEWS and only
        allows leaving one review per user and product.

        Override this if you want to alter the default behaviour; e.g. enforce
        that a user purchased the product to be allowed to leave a review.

        确定用户是否可以在此产品上添加评论。
        默认实现仅限于OSCAR_ALLOW_ANON_REVIEWS允许每个用户和产品留下一个评论。
        如果要更改默认行为，请覆盖此项; 例如 强制用户购买产品以允许其进行审核。
        """
        if user.is_authenticated or settings.OSCAR_ALLOW_ANON_REVIEWS:
            return not self.has_review_by(user)
        else:
            return False

    @cached_property
    def num_approved_reviews(self):
        return self.reviews.approved().count()

    # 分类推荐产品
    @property
    def sorted_recommended_products(self):
        """Keeping order by recommendation ranking."""
        # 通过推荐排名保持秩序
        return [r.recommendation for r in self.primary_recommendations
                                              .select_related('recommendation').all()]


# 抽象产品推荐
class AbstractProductRecommendation(models.Model):
    """
    'Through' model for product recommendations
    ‘Through’模块是为了推荐产品
    """
    primary = models.ForeignKey(
        'catalogue.Product',
        on_delete=models.CASCADE,
        related_name='primary_recommendations',
        verbose_name=_("Primary product"))
    recommendation = models.ForeignKey(
        'catalogue.Product',
        on_delete=models.CASCADE,
        verbose_name=_("Recommended product"))
    ranking = models.PositiveSmallIntegerField(
        _('Ranking'), default=0,
        # 确定产品的顺序。 具有较高价值的产品将出现在排名较低的产品之前。
        help_text=_('Determines order of the products. A product with a higher'
                    ' value will appear before one with a lower ranking.'))

    class Meta:
        abstract = True
        app_label = 'catalogue'
        ordering = ['primary', '-ranking']
        unique_together = ('primary', 'recommendation')
        verbose_name = _('Product recommendation')
        verbose_name_plural = _('Product recomendations')


# 抽象产品属性
class AbstractProductAttribute(models.Model):
    """
    Defines an attribute for a product class. (For example, number_of_pages for
    a 'book' class)
    定义产品类的属性。 （例如，'book'类的number_of_pages）
    """
    product_class = models.ForeignKey(
        'catalogue.ProductClass',
        blank=True,
        on_delete=models.CASCADE,
        related_name='attributes',
        null=True,
        verbose_name=_("Product type"))
    name = models.CharField(_('Name'), max_length=128)
    code = models.SlugField(
        _('Code'), max_length=128,
        # 代码只能包含字母a-z，A-Z，数字和下划线，并且不能以数字开头
        validators=[
            RegexValidator(
                regex=r'^[a-zA-Z_][0-9a-zA-Z_]*$',
                message=_(
                    "Code can only contain the letters a-z, A-Z, digits, "
                    "and underscores, and can't start with a digit.")),
            non_python_keyword
        ])

    # Attribute types 属性类型
    TEXT = "text"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    FLOAT = "float"
    RICHTEXT = "richtext"
    DATE = "date"
    DATETIME = "datetime"
    OPTION = "option"
    MULTI_OPTION = "multi_option"
    ENTITY = "entity"
    FILE = "file"
    IMAGE = "image"
    TYPE_CHOICES = (
        (TEXT, _("Text")),
        (INTEGER, _("Integer")),
        (BOOLEAN, _("True / False")),
        (FLOAT, _("Float")),
        (RICHTEXT, _("Rich Text")),
        (DATE, _("Date")),
        (DATETIME, _("Datetime")),
        (OPTION, _("Option")),
        (MULTI_OPTION, _("Multi Option")),
        (ENTITY, _("Entity")),
        (FILE, _("File")),
        (IMAGE, _("Image")),
    )
    type = models.CharField(
        choices=TYPE_CHOICES, default=TYPE_CHOICES[0][0],
        max_length=20, verbose_name=_("Type"))

    option_group = models.ForeignKey(
        'catalogue.AttributeOptionGroup',
        blank=True,
        null=True,
        on_delete=models.CASCADE,
        related_name='product_attributes',
        verbose_name=_("Option Group"),
        # 如果使用“选项”或“多选项”类型，请选择一个选项组
        help_text=_('Select an option group if using type "Option" or "Multi Option"'))
    required = models.BooleanField(_('Required'), default=False)

    class Meta:
        abstract = True
        app_label = 'catalogue'
        ordering = ['code']
        verbose_name = _('Product attribute')
        verbose_name_plural = _('Product attributes')

    @property
    def is_option(self):
        return self.type == self.OPTION

    @property
    def is_multi_option(self):
        return self.type == self.MULTI_OPTION

    @property
    def is_file(self):
        return self.type in [self.FILE, self.IMAGE]

    def __str__(self):
        return self.name

    def _save_file(self, value_obj, value):
        # File fields in Django are treated differently, see
        # django.db.models.fields.FileField and method save_form_data
        # Django中的文件字段有不同的处理方式，请
        # 参阅django.db.models.fields.FileField和方法save_form_data
        if value is None:
            # No change
            return
        elif value is False:
            # Delete file
            value_obj.delete()
        else:
            # New uploaded file 新上传的文件
            value_obj.value = value
            value_obj.save()

    def _save_multi_option(self, value_obj, value):
        # ManyToMany fields are handled separately
        # ManyToMany字段分别处理
        if value is None:
            value_obj.delete()
            return
        try:
            count = value.count()
        except (AttributeError, TypeError):
            count = len(value)
        if count == 0:
            value_obj.delete()
        else:
            value_obj.value = value
            value_obj.save()

    def _save_value(self, value_obj, value):
        if value is None or value == '':
            value_obj.delete()
            return
        if value != value_obj.value:
            value_obj.value = value
            value_obj.save()

    def save_value(self, product, value):   # noqa: C901 too complex  noqa：C901太复杂了
        ProductAttributeValue = get_model('catalogue', 'ProductAttributeValue')
        try:
            value_obj = product.attribute_values.get(attribute=self)
        except ProductAttributeValue.DoesNotExist:
            # FileField uses False for announcing deletion of the file
            # not creating a new value
            # FileField使用False来宣告删除不创建新值的文件
            delete_file = self.is_file and value is False
            if value is None or value == '' or delete_file:
                return
            value_obj = ProductAttributeValue.objects.create(
                product=product, attribute=self)

        if self.is_file:
            self._save_file(value_obj, value)
        elif self.is_multi_option:
            self._save_multi_option(value_obj, value)
        else:
            self._save_value(value_obj, value)

    def validate_value(self, value):
        validator = getattr(self, '_validate_%s' % self.type)
        validator(value)

    # Validators 验证器

    def _validate_text(self, value):
        if not isinstance(value, str):
            # 必须是str
            raise ValidationError(_("Must be str"))
    _validate_richtext = _validate_text

    def _validate_float(self, value):
        try:
            float(value)
        except ValueError:
            # 必须是一个浮点数
            raise ValidationError(_("Must be a float"))

    def _validate_integer(self, value):
        try:
            int(value)
        except ValueError:
            # 必须是整数
            raise ValidationError(_("Must be an integer"))

    def _validate_date(self, value):
        if not (isinstance(value, datetime) or isinstance(value, date)):
            # 必须是日期或日期时间
            raise ValidationError(_("Must be a date or datetime"))

    def _validate_datetime(self, value):
        # 必须是日期时间
        if not isinstance(value, datetime):
            raise ValidationError(_("Must be a datetime"))

    # 验证布尔值
    def _validate_boolean(self, value):
        # 必须是布尔值
        if not type(value) == bool:
            raise ValidationError(_("Must be a boolean"))

    # 验证实体
    def _validate_entity(self, value):
        # 必须是模型实例
        if not isinstance(value, models.Model):
            raise ValidationError(_("Must be a model instance"))

    # 验证多选项
    def _validate_multi_option(self, value):
        try:
            values = iter(value)
        # 必须是列表或属性选项查询集
        except TypeError:
            raise ValidationError(
                _("Must be a list or AttributeOption queryset"))
        # Validate each value as if it were an option
        # Pass in valid_values so that the DB isn't hit multiple times per iteration
        # 验证每个值，就好像它是一个选项传递有效值，以便每次迭代不会多次命中DB
        valid_values = self.option_group.options.values_list(
            'option', flat=True)
        for value in values:
            self._validate_option(value, valid_values=valid_values)

    # 验证选项
    def _validate_option(self, value, valid_values=None):
        if not isinstance(value, get_model('catalogue', 'AttributeOption')):
            # 必须是属性选项模型对象实例
            raise ValidationError(
                _("Must be an AttributeOption model object instance"))
        if not value.pk:
            # 属性选项尚未保存
            raise ValidationError(_("AttributeOption has not been saved yet"))
        if valid_values is None:
            valid_values = self.option_group.options.values_list(
                'option', flat=True)
        if value.option not in valid_values:
            # 这不是一个有效的选择
            raise ValidationError(
                _("%(enum)s is not a valid choice for %(attr)s") %
                {'enum': value, 'attr': self})

    # 验证文件
    def _validate_file(self, value):
        if value and not isinstance(value, File):
            # 必须是文件字段
            raise ValidationError(_("Must be a file field"))
    _validate_image = _validate_file


# 抽象产品属性值
class AbstractProductAttributeValue(models.Model):
    """
    The "through" model for the m2m relationship between catalogue.Product and
    catalogue.ProductAttribute.  This specifies the value of the attribute for
    a particular product

    For example: number_of_pages = 295

    目录产品(catalogue.Product)和目录产品属性(catalogue.ProductAttribut)之间
    的m2m关系的'through'模型。 这指定了特定产品的属性值
    例如：页数= 295
    """
    attribute = models.ForeignKey(
        'catalogue.ProductAttribute',
        on_delete=models.CASCADE,
        verbose_name=_("Attribute"))
    product = models.ForeignKey(
        'catalogue.Product',
        on_delete=models.CASCADE,
        related_name='attribute_values',
        verbose_name=_("Product"))

    value_text = models.TextField(_('Text'), blank=True, null=True)
    value_integer = models.IntegerField(_('Integer'), blank=True, null=True)
    value_boolean = models.NullBooleanField(_('Boolean'), blank=True)
    value_float = models.FloatField(_('Float'), blank=True, null=True)
    value_richtext = models.TextField(_('Richtext'), blank=True, null=True)
    value_date = models.DateField(_('Date'), blank=True, null=True)
    value_datetime = models.DateTimeField(_('DateTime'), blank=True, null=True)
    value_multi_option = models.ManyToManyField(
        'catalogue.AttributeOption', blank=True,
        related_name='multi_valued_attribute_values',
        verbose_name=_("Value multi option"))
    value_option = models.ForeignKey(
        'catalogue.AttributeOption',
        blank=True,
        null=True,
        on_delete=models.CASCADE,
        verbose_name=_("Value option"))
    value_file = models.FileField(
        upload_to=settings.OSCAR_IMAGE_FOLDER, max_length=255,
        blank=True, null=True)
    value_image = models.ImageField(
        upload_to=settings.OSCAR_IMAGE_FOLDER, max_length=255,
        blank=True, null=True)
    value_entity = GenericForeignKey(
        'entity_content_type', 'entity_object_id')

    entity_content_type = models.ForeignKey(
        ContentType,
        blank=True,
        editable=False,
        on_delete=models.CASCADE,
        null=True)
    entity_object_id = models.PositiveIntegerField(
        null=True, blank=True, editable=False)

    def _get_value(self):
        value = getattr(self, 'value_%s' % self.attribute.type)
        if hasattr(value, 'all'):
            value = value.all()
        return value

    def _set_value(self, new_value):
        attr_name = 'value_%s' % self.attribute.type

        if self.attribute.is_option and isinstance(new_value, str):
            # Need to look up instance of AttributeOption
            # 需要查找属性选项的实例
            new_value = self.attribute.option_group.options.get(
                option=new_value)
        elif self.attribute.is_multi_option:
            getattr(self, attr_name).set(new_value)
            return

        setattr(self, attr_name, new_value)
        return

    value = property(_get_value, _set_value)

    class Meta:
        abstract = True
        app_label = 'catalogue'
        unique_together = ('attribute', 'product')
        verbose_name = _('Product attribute value')
        verbose_name_plural = _('Product attribute values')

    def __str__(self):
        return self.summary()

    # 概要
    def summary(self):
        """
        Gets a string representation of both the attribute and it's value,
        used e.g in product summaries.

        获取属性及其值的字符串表示形式，例如在产品摘要中使用。
        """
        return "%s: %s" % (self.attribute.name, self.value_as_text)

    @property
    def value_as_text(self):
        """
        Returns a string representation of the attribute's value. To customise
        e.g. image attribute values, declare a _image_as_text property and
        return something appropriate.

        返回属性值的字符串表示形式。 要定制，例如 图像属性值，
        声明_image_as_text属性并返回适当的内容。
        """
        property_name = '_%s_as_text' % self.attribute.type
        return getattr(self, property_name, self.value)

    # 文本多选项
    @property
    def _multi_option_as_text(self):
        return ', '.join(str(option) for option in self.value_multi_option.all())

    @property
    def _richtext_as_text(self):
        return strip_tags(self.value)

    @property
    def _entity_as_text(self):
        """
        Returns the unicode representation of the related model. You likely
        want to customise this (and maybe _entity_as_html) if you use entities.
        返回相关模型的unicode表示形式。 如果您使用实体，您可能想要
        自定义此（以及可能_entity_as_html）。
        """
        return str(self.value)

    @property
    def value_as_html(self):
        """
        Returns a HTML representation of the attribute's value. To customise
        e.g. image attribute values, declare a _image_as_html property and
        return e.g. an <img> tag.  Defaults to the _as_text representation.

        返回属性值的HTML表示形式。 要定制，例如 图像属性值，
        声明_image_as_html属性并返回例如 一个<img>标签。 默认为_as_text表示。
        """
        property_name = '_%s_as_html' % self.attribute.type
        return getattr(self, property_name, self.value_as_text)

    @property
    def _richtext_as_html(self):
        return mark_safe(self.value)

# 抽象属性选项组
class AbstractAttributeOptionGroup(models.Model):
    """
    Defines a group of options that collectively may be used as an
    attribute type

    For example, Language

    定义一组可共同用作属性类型的选项
    例如，语言
    """
    name = models.CharField(_('Name'), max_length=128)

    def __str__(self):
        return self.name

    class Meta:
        abstract = True
        app_label = 'catalogue'
        verbose_name = _('Attribute option group')
        verbose_name_plural = _('Attribute option groups')

    @property
    def option_summary(self):
        options = [o.option for o in self.options.all()]
        return ", ".join(options)


class AbstractAttributeOption(models.Model):
    """
    Provides an option within an option group for an attribute type
    Examples: In a Language group, English, Greek, French

    在属性类型的选项组中提供选项
    示例：在语言组中，英语，希腊语，法语
    """
    group = models.ForeignKey(
        'catalogue.AttributeOptionGroup',
        on_delete=models.CASCADE,
        related_name='options',
        verbose_name=_("Group"))
    option = models.CharField(_('Option'), max_length=255)

    def __str__(self):
        return self.option

    class Meta:
        abstract = True
        app_label = 'catalogue'
        unique_together = ('group', 'option')
        verbose_name = _('Attribute option')
        verbose_name_plural = _('Attribute options')


# 抽象选项
class AbstractOption(models.Model):
    """
    An option that can be selected for a particular item when the product
    is added to the basket.

    For example,  a list ID for an SMS message send, or a personalised message
    to print on a T-shirt.

    This is not the same as an 'attribute' as options do not have a fixed value
    for a particular item.  Instead, option need to be specified by a customer
    when they add the item to their basket.
    将产品添加到购物篮时可以为特定商品选择的选项
    例如，SMS消息发送的列表ID或个性化消息在T恤上打印。
    这与“属性”不同，因为选项没有特定项目的固定值。 相反，当客户将商品
    添加到购物篮时，需要由顾客指定选项。
    """
    name = models.CharField(_("Name"), max_length=128)
    code = AutoSlugField(_("Code"), max_length=128, unique=True,
                         populate_from='name')

    REQUIRED, OPTIONAL = ('Required', 'Optional')
    TYPE_CHOICES = (
        (REQUIRED, _("Required - a value for this option must be specified")),
        (OPTIONAL, _("Optional - a value for this option can be omitted")),
    )
    # 必需 - 必须指定此选项的值
    # 可选 - 可以省略此选项的值
    type = models.CharField(_("Status"), max_length=128, default=REQUIRED,
                            choices=TYPE_CHOICES)

    class Meta:
        abstract = True
        app_label = 'catalogue'
        verbose_name = _("Option")
        verbose_name_plural = _("Options")

    def __str__(self):
        return self.name

    @property
    def is_required(self):
        return self.type == self.REQUIRED


# 缺少产品图片
class MissingProductImage(object):

    """
    Mimics a Django file field by having a name property.

    sorl-thumbnail requires all it's images to be in MEDIA_ROOT. This class
    tries symlinking the default "missing image" image in STATIC_ROOT
    into MEDIA_ROOT for convenience, as that is necessary every time an Oscar
    project is setup. This avoids the less helpful NotFound IOError that would
    be raised when sorl-thumbnail tries to access it.

    通过具有name属性来模仿Django文件字段。
    sorl-thumbnail要求所有图像都在MEDIA_ROOT中。 为方便起见，此类尝试
    将STATIC_ROOT中的默认“缺失图像”图像符号链接到MEDIA_ROOT，
    因为每次设置Oscar项目时都需要这样做。 这避免了当sorl-thumbnail尝试访问它时
    会引发的不太有用的NotFound IOError。
    """

    def __init__(self, name=None):
        self.name = name if name else settings.OSCAR_MISSING_IMAGE_URL
        media_file_path = os.path.join(settings.MEDIA_ROOT, self.name)
        # don't try to symlink if MEDIA_ROOT is not set (e.g. running tests)
        # 如果未设置MEDIA_ROOT，则不要尝试符号链接（例如，运行测试）
        if settings.MEDIA_ROOT and not os.path.exists(media_file_path):
            self.symlink_missing_image(media_file_path)

    def symlink_missing_image(self, media_file_path):
        static_file_path = find('oscar/img/%s' % self.name)
        if static_file_path is not None:
            try:
                # Check that the target directory exists, and attempt to
                # create it if it doesn't.
                # 检查目标目录是否存在，如果不存在则尝试创建目标目录。
                media_file_dir = os.path.dirname(media_file_path)
                if not os.path.exists(media_file_dir):
                    os.makedirs(media_file_dir)
                os.symlink(static_file_path, media_file_path)
            except OSError:
                raise ImproperlyConfigured((
                    "Please copy/symlink the "
                    "'missing image' image at %s into your MEDIA_ROOT at %s. "
                    "This exception was raised because Oscar was unable to "
                    "symlink it for you.") % (media_file_path,
                                              settings.MEDIA_ROOT))
            else:
                logging.info((
                    "Symlinked the 'missing image' image at %s into your "
                    "MEDIA_ROOT at %s") % (media_file_path,
                                           settings.MEDIA_ROOT))


# 抽象产品图像
class AbstractProductImage(models.Model):
    """
    An image of a product
    产品的图像
    """
    product = models.ForeignKey(
        'catalogue.Product',
        on_delete=models.CASCADE,
        related_name='images',
        verbose_name=_("Product"))
    original = models.ImageField(
        _("Original"), upload_to=settings.OSCAR_IMAGE_FOLDER, max_length=255)
    caption = models.CharField(_("Caption"), max_length=200, blank=True)

    #: Use display_order to determine which is the "primary" image
    # 使用display_order确定哪个是“主”图像
    display_order = models.PositiveIntegerField(
        _("Display order"), default=0,
        help_text=_("An image with a display order of zero will be the primary"
                    " image for a product"))
    # 显示顺序为零的图像将是产品的主要图像
    date_created = models.DateTimeField(_("Date created"), auto_now_add=True)

    class Meta:
        abstract = True
        app_label = 'catalogue'
        # Any custom models should ensure that this ordering is unchanged, or
        # your query count will explode. See AbstractProduct.primary_image.
        # 任何自定义模型都应确保此顺序不变，否则您的查询计数将会爆炸。
        # 请参见AbstractProduct.primary_image。
        ordering = ["display_order"]
        verbose_name = _('Product image')
        verbose_name_plural = _('Product images')

    def __str__(self):
        return "Image of '%s'" % self.product

    def is_primary(self):
        """
        Return bool if image display order is 0
        如果图像显示顺序为0，则返回bool
        """
        return self.display_order == 0

    def delete(self, *args, **kwargs):
        """
        Always keep the display_order as consecutive integers. This avoids
        issue #855.
        始终将display_order保持为连续整数。 这避免了问题#855.
        """
        super().delete(*args, **kwargs)
        for idx, image in enumerate(self.product.images.all()):
            image.display_order = idx
            image.save()
