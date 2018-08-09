from django.core.paginator import InvalidPage, Paginator
from django.utils.translation import gettext_lazy as _
from haystack import connections

from oscar.core.loading import get_class

from . import facets

FacetMunger = get_class('search.facets', 'FacetMunger')


class SearchHandler(object):
    """
    A class that is concerned with performing a search and paginating the
    results. The search is triggered upon initialisation (mainly to have a
    predictable point to process any errors).  Search results are cached, so
    they can be accessed multiple times without incurring any overhead.

    The raison d'etre for this third way to interface with Haystack is
    two-fold. The Haystack search form doesn't do enough for our needs, and
    basing a view off a Haystack search view is unnecessarily invasive.
    Furthermore, using our own search handler means it is easy to swap
    out Haystack, which has been considered before.

    Usage:

        handler = SearchHandler(request.GET, request.get_full_path)
        found_objects = handler.get_paginated_objects()
        context = handler.get_search_context_data()

    Error handling:

        You need to catch an InvalidPage exception which gets thrown when an
        invalid page number is supplied.

    与执行搜索和分页结果有关的类。 初始化时触发搜索（主要是为了有一个可预测的点来
    处理任何错误）。 搜索结果被缓存，因此可以多次访问它们而不会产生任何开销。

    第三种与 Haystack (django中的全文检索功能) 接口的方式的存在理由是双重的。
    Haystack搜索表单不能满足我们的需求，并且基于Haystack搜索视图的视图是
    不必要的侵入性。 此外，使用我们自己的搜索处理程序意味着可以轻松更换之
    前已经考虑过的Haystack。

    用法：
        handler = SearchHandler(request.GET, request.get_full_path)
        found_objects = handler.get_paginated_objects()
        context = handler.get_search_context_data()
    错误处理：
        您需要捕获在提供无效页码时抛出的InvalidPage异常。
    """

    form_class = None
    model_whitelist = None
    paginate_by = None
    paginator_class = Paginator
    page_kwarg = 'page'

    def __init__(self, request_data, full_path):
        self.full_path = full_path
        self.request_data = request_data

        # Triggers the search.
        # 触发搜索。
        search_queryset = self.get_search_queryset()
        self.search_form = self.get_search_form(
            request_data, search_queryset)
        self.results = self.get_search_results(self.search_form)
        # If below raises an UnicodeDecodeError, you're running pysolr < 3.2
        # with Solr 4.
        # 如果下面引发UnicodeDecodeError，则使用Solr 4运行pysolr <3.2。
        self.paginator, self.page = self.paginate_queryset(
            self.results, request_data)

    # Search related methods 搜索相关方法

    def get_search_results(self, search_form):
        """
        Perform the actual search using Haystack's search form. Returns
        a SearchQuerySet. The SQS is empty if the form is invalid.
        使用Haystack的搜索表单执行实际搜索。 返回SearchQuerySet。 如果表单
        无效，则SQS为空。
        """
        return search_form.search()

    def get_search_form(self, request_data, search_queryset, **form_kwargs):
        """
        Return a bound version of Haystack's search form.
        返回Haystack搜索表单的绑定版本。
        """
        kwargs = {
            'data': request_data,
            'selected_facets': request_data.getlist("selected_facets"),
            'searchqueryset': search_queryset
        }
        kwargs.update(**form_kwargs)
        return self.form_class(**kwargs)

    def get_search_queryset(self):
        """
        Returns the search queryset that is used as a base for the search.
        返回用作搜索基础的搜索查询集。
        """
        sqs = facets.base_sqs()
        if self.model_whitelist:
            # Limit queryset to specified list of models
            # 将查询集限制为指定的模型列表
            sqs = sqs.models(*self.model_whitelist)
        return sqs

    # Pagination related methods
    # 分页相关方法

    def paginate_queryset(self, queryset, request_data):
        """
        Paginate the search results. This is a simplified version of
        Django's MultipleObjectMixin.paginate_queryset
        分页搜索结果。 这是Django的MultipleObjectMixin.paginate_queryset的简化版本
        """
        paginator = self.get_paginator(queryset)
        page_kwarg = self.page_kwarg
        page = request_data.get(page_kwarg, 1)
        try:
            page_number = int(page)
        except ValueError:
            if page == 'last':
                page_number = paginator.num_pages
            else:
                raise InvalidPage(_(
                    "Page is not 'last', nor can it be converted to an int."))
        # This can also raise an InvalidPage exception.
        # 这也可能引发InvalidPage异常。
        return paginator, paginator.page(page_number)

    def get_paginator(self, queryset):
        """
        Return a paginator. Override this to set settings like orphans,
        allow_empty, etc.
        返回一个分页器。 覆盖它以设置像孤儿，allow_empty等设置。
        """
        return self.paginator_class(queryset, self.paginate_by)

    # Accessing the search results and meta data
    # 访问搜索结果和元数据

    def bulk_fetch_results(self, paginated_results):
        """
        This method gets paginated search results and returns a list of Django
        objects in the same order.

        It preserves the order without doing any ordering in Python, even
        when more than one Django model are returned in the search results. It
        also uses the same queryset that was used to populate the search
        queryset, so any select_related/prefetch_related optimisations are
        in effect.

        It is heavily based on Haystack's SearchQuerySet.post_process_results,
        but works on the paginated results instead of all of them.

        此方法获取分页搜索结果并以相同顺序返回Django对象列表。

        即使在搜索结果中返回了多个Django模型，它也不会在Python中进行任何排序而
        保留顺序。 它还使用与填充搜索查询集相同的查询集，因此任何
        select_related / prefetch_related优化都有效。

        它主要基于Haystack的SearchQuerySet.post_process_results，但是对
        分页结果而不是所有结果起作用。
        """
        objects = []

        models_pks = loaded_objects = {}
        for result in paginated_results:
            models_pks.setdefault(result.model, []).append(result.pk)

        search_backend_alias = self.results.query.backend.connection_alias
        for model in models_pks:
            ui = connections[search_backend_alias].get_unified_index()
            index = ui.get_index(model)
            queryset = index.read_queryset(using=search_backend_alias)
            loaded_objects[model] = queryset.in_bulk(models_pks[model])

        for result in paginated_results:
            model_objects = loaded_objects.get(result.model, {})
            try:
                result._object = model_objects[int(result.pk)]
            except KeyError:
                # The object was either deleted since we indexed or should
                # be ignored; fail silently.
                # 该对象要么被删除，要么我们索引或应该被忽略; 安静地失败。
                pass
            else:
                objects.append(result._object)

        return objects

    def get_paginated_objects(self):
        """
        Return a paginated list of Django model instances. The call is cached.
        返回Django模型实例的分页列表。 呼叫被缓存。
        """
        if hasattr(self, '_objects'):
            return self._objects
        else:
            paginated_results = self.page.object_list
            self._objects = self.bulk_fetch_results(paginated_results)
        return self._objects

    def get_facet_munger(self):
        return FacetMunger(
            self.full_path,
            self.search_form.selected_multi_facets,
            self.results.facet_counts())

    def get_search_context_data(self, context_object_name=None):
        """
        Return metadata about the search in a dictionary useful to populate
        template contexts. If you pass in a context_object_name, the dictionary
        will also contain the actual list of found objects.

        The expected usage is to call this function in your view's
        get_context_data:

            search_context = self.search_handler.get_search_context_data(
                self.context_object_name)
            context.update(search_context)
            return context

        在有用于填充模板上下文的字典中返回有关搜索的元数据。 如果传
        入context_object_name，则字典还将包含找到的对象的实际列表。

        预期的用法是在视图的get_context_data中调用此函数：
            search_context = self.search_handler.get_search_context_data(
            self.context_object_name)
            context.update(search_context)
            return context
        """

        # Use the FacetMunger to convert Haystack's awkward facet data into
        # something the templates can use.
        # Note that the FacetMunger accesses object_list (unpaginated results),
        # whereas we use the paginated search results to populate the context
        # with products
        # 使用Facet Munger将Haystacks笨拙的facet数据转换为模板可以使用的东西。
        # 请注意，FacetMunger访问object_list（取消标记的结果），而我们使用分页搜
        # 索结果用产品填充上下文
        munger = self.get_facet_munger()
        facet_data = munger.facet_data()
        has_facets = any([data['results'] for data in facet_data.values()])

        context = {
            'facet_data': facet_data,
            'has_facets': has_facets,
            # This is a serious code smell; we just pass through the selected
            # facets data to the view again, and the template adds those
            # as fields to the form. This hack ensures that facets stay
            # selected when changing relevancy.
            # 这是一种严重的代码味道; 我们只是将选定的facets数据再次传递给视图，
            # 然后模板将这些数据作为字段添加到表单中。 此hack确保在更改相关性时
            # 保持选择方面。
            'selected_facets': self.request_data.getlist('selected_facets'),
            'form': self.search_form,
            'paginator': self.paginator,
            'page_obj': self.page,
        }

        # It's a pretty common pattern to want the actual results in the
        # context, so pass them in if context_object_name is set.
        # 在上下文中需要实际结果是一种非常常见的模式，因此如果设置
        # 了context_object_name，则将它们传入。
        if context_object_name is not None:
            context[context_object_name] = self.get_paginated_objects()

        return context
