from django.conf import settings
from django.utils.module_loading import import_string
from django.views.generic.list import MultipleObjectMixin

from oscar.core.loading import get_class, get_model

BrowseCategoryForm = get_class('search.forms', 'BrowseCategoryForm')
SearchHandler = get_class('search.search_handlers', 'SearchHandler')
is_solr_supported = get_class('search.features', 'is_solr_supported')
is_elasticsearch_supported = get_class('search.features', 'is_elasticsearch_supported')
Product = get_model('catalogue', 'Product')


# 获得产品搜索处理程序类
def get_product_search_handler_class():
    """
    Determine the search handler to use.

    Currently only Solr is supported as a search backend, so it falls
    back to rudimentary category browsing if that isn't enabled.

    确定要使用的搜索处理程序。
    目前只支持Solr作为搜索后端，因此如果未启用，则会回退到基本类别浏览。
    """
    # Use get_class to ensure overridability
    # 使用get_class确保可覆盖性
    if settings.OSCAR_PRODUCT_SEARCH_HANDLER is not None:
        return import_string(settings.OSCAR_PRODUCT_SEARCH_HANDLER)
    if is_solr_supported():
        return get_class('catalogue.search_handlers', 'SolrProductSearchHandler')
    elif is_elasticsearch_supported():
        return get_class(
            'catalogue.search_handlers', 'ESProductSearchHandler',
        )
    else:
        return get_class(
            'catalogue.search_handlers', 'SimpleProductSearchHandler')


# Solr产品搜索处理程序
class SolrProductSearchHandler(SearchHandler):
    """
    Search handler specialised for searching products.  Comes with optional
    category filtering. To be used with a Solr search backend.

    搜索处理程序专门用于搜索产品 附带可选的类别过滤功能。 与Solr搜索后端一起使用。
    """
    form_class = BrowseCategoryForm
    model_whitelist = [Product]
    paginate_by = settings.OSCAR_PRODUCTS_PER_PAGE

    def __init__(self, request_data, full_path, categories=None):
        self.categories = categories
        super().__init__(request_data, full_path)

    # 获取搜索查询集
    def get_search_queryset(self):
        sqs = super().get_search_queryset()
        if self.categories:
            # We use 'narrow' API to ensure Solr's 'fq' filtering is used as
            # opposed to filtering using 'q'.
            # 我们使用'narrow'API来确保使用Solr的'fq'过滤而不是使用'q'进行过滤。
            pattern = ' OR '.join([
                '"%s"' % sqs.query.clean(c.full_name) for c in self.categories])
            sqs = sqs.narrow('category_exact:(%s)' % pattern)
        return sqs


# ES产品搜索处理程序
class ESProductSearchHandler(SearchHandler):
    """
    Search handler specialised for searching products.  Comes with optional
    category filtering. To be used with an ElasticSearch search backend.

    搜索处理程序专门用于搜索产品 附带可选的类别过滤功能。
     与ElasticSearch搜索后端一起使用。
    """
    form_class = BrowseCategoryForm
    model_whitelist = [Product]
    paginate_by = settings.OSCAR_PRODUCTS_PER_PAGE

    def __init__(self, request_data, full_path, categories=None):
        self.categories = categories
        super().__init__(request_data, full_path)

    # 获取搜索查询集
    def get_search_queryset(self):
        sqs = super().get_search_queryset()
        if self.categories:
            for category in self.categories:
                sqs = sqs.filter_or(category=category.full_name)
        return sqs


# 简单的产品搜索处理程序
class SimpleProductSearchHandler(MultipleObjectMixin):
    """
    A basic implementation of the full-featured SearchHandler that has no
    faceting support, but doesn't require a Haystack backend. It only
    supports category browsing.

    Note that is meant as a replacement search handler and not as a view
    mixin; the mixin just does most of what we need it to do.

    功能齐全的SearchHandler的基本实现，没有分面支持，但不需要Haystack后端。
    它仅支持类别浏览。
    注意，这意味着替换搜索处理程序而不是视图mixin;
    mixin只是完成了我们需要它做的大部分工作。
    """
    paginate_by = settings.OSCAR_PRODUCTS_PER_PAGE

    def __init__(self, request_data, full_path, categories=None):
        self.categories = categories
        self.kwargs = {'page': request_data.get('page', 1)}
        self.object_list = self.get_queryset()

    # 获取查询集
    def get_queryset(self):
        qs = Product.browsable.base_queryset()
        if self.categories:
            qs = qs.filter(categories__in=self.categories).distinct()
        return qs

    # 获取搜索上下文数据
    def get_search_context_data(self, context_object_name):
        # Set the context_object_name instance property as it's needed
        # internally by MultipleObjectMixin
        # 在MultipleObjectMixin内部需要设置context_object_name实例属性
        self.context_object_name = context_object_name
        context = self.get_context_data(object_list=self.object_list)
        context[context_object_name] = context['page_obj'].object_list
        return context
