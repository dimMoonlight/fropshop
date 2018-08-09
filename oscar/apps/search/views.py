from haystack import views

from oscar.apps.search.signals import user_search
from oscar.core.loading import get_class, get_model

Product = get_model('catalogue', 'Product')
FacetMunger = get_class('search.facets', 'FacetMunger')


class FacetedSearchView(views.FacetedSearchView):
    """
    A modified version of Haystack's FacetedSearchView

    Note that facets are configured when the ``SearchQuerySet`` is initialised.
    This takes place in the search application class.

    See https://django-haystack.readthedocs.io/en/v2.1.0/views_and_forms.html#facetedsearchform # noqa

    Haystack的FacetedSearchView的修改版本
    请注意，在初始化``SearchQuerySet``时配置facet。 这发生在搜索应用程序类中。
    参见 https://django-haystack.readthedocs.io/en/v2.1.0/views_and_forms.html#facetedsearchform # noqa
    """

    # Haystack uses a different class attribute to CBVs
    # Haystack对CBV使用不同的类属性
    template = "search/results.html"
    search_signal = user_search

    def __call__(self, request):
        response = super().__call__(request)

        # Raise a signal for other apps to hook into for analytics
        # 为其他应用程序提出信号以进行分析
        self.search_signal.send(
            sender=self, session=self.request.session,
            user=self.request.user, query=self.query)

        return response

    # Override this method to add the spelling suggestion to the context and to
    # convert Haystack's default facet data into a more useful structure so we
    # have to do less work in the template.
    # 重写此方法以将拼写建议添加到上下文并将Haystack的默认构面数据转换为更有
    # 用的结构，因此我们必须在模板中执行更少的工作。
    def extra_context(self):
        extra = super().extra_context()

        # Show suggestion no matter what.  Haystack 2.1 only shows a suggestion
        # if there are some results, which seems a bit weird to me.
        # 无论如何显示建议。 Haystack 2.1只显示一个建议，如果有一些结果，这对我
        # 来说似乎有点奇怪。
        if self.results.query.backend.include_spelling:
            # Note, this triggers an extra call to the search backend
            # 注意，这会触发对搜索后端的额外调用
            suggestion = self.form.get_suggestion()
            if suggestion != self.query:
                extra['suggestion'] = suggestion

        # Convert facet data into a more useful data structure
        # 将刻面数据转换为更有用的数据结构
        if 'fields' in extra['facets']:
            munger = FacetMunger(
                self.request.get_full_path(),
                self.form.selected_multi_facets,
                self.results.facet_counts())
            extra['facet_data'] = munger.facet_data()
            has_facets = any([len(data['results']) for
                              data in extra['facet_data'].values()])
            extra['has_facets'] = has_facets

        # Pass list of selected facets so they can be included in the sorting
        # form.
        # 通过所选方面的列表，以便它们可以包含在排序表单中。
        extra['selected_facets'] = self.request.GET.getlist('selected_facets')

        return extra

    def get_results(self):
        # We're only interested in products (there might be other content types
        # in the Solr index).
        # 我们只对产品感兴趣（Solr索引中可能还有其他内容类型）。
        return super().get_results().models(Product)
