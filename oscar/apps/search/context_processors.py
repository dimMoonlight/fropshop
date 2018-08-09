from oscar.core.loading import get_class

SearchForm = get_class('search.forms', 'SearchForm')


def search_form(request):
    """
    Ensure that the search form is available site wide
    确保搜索表单在站点范围内可用
    """
    return {'search_form': SearchForm(request.GET)}
