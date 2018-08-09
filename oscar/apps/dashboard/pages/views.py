from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpResponseRedirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views import generic
from django.views.generic import ListView

from oscar.core.loading import get_classes, get_model
from oscar.core.utils import slugify
from oscar.core.validators import URLDoesNotExistValidator

FlatPage = get_model('flatpages', 'FlatPage')
Site = get_model('sites', 'Site')
PageSearchForm, PageUpdateForm = get_classes('dashboard.pages.forms', ('PageSearchForm', 'PageUpdateForm'))


# 页面列表视图
class PageListView(ListView):
    """
    View for listing all existing flatpages.
    视图列出所有现有的平版页。
    """
    template_name = 'dashboard/pages/index.html'
    model = FlatPage
    form_class = PageSearchForm
    paginate_by = settings.OSCAR_DASHBOARD_ITEMS_PER_PAGE
    desc_template = '%(main_filter)s %(title_filter)s'

    def get_queryset(self):
        """
        Get queryset of all flatpages to be displayed. If a
        search term is specified in the search form, it will be used
        to filter the queryset.
        获取要显示的所有flatpages的查询集。 如果在搜索表单中指定了搜
        索词，则它将用于过滤查询集。
        """
        self.desc_ctx = {
            'main_filter': _('All pages'),
            'title_filter': '',
        }
        queryset = self.model.objects.all().order_by('title')

        self.form = self.form_class(self.request.GET)
        if not self.form.is_valid():
            return queryset

        data = self.form.cleaned_data

        if data['title']:
            queryset = queryset.filter(title__icontains=data['title'])
            self.desc_ctx['title_filter'] \
                = _(" with title containing '%s'") % data['title']

        return queryset

    def get_context_data(self, **kwargs):
        """
        Get context data with *form* and *queryset_description* data
        added to it.
        获取带有* form *和* queryset_description *数据的上下文数据。
        """
        context = super().get_context_data(**kwargs)
        context['form'] = self.form
        context['queryset_description'] = self.desc_template % self.desc_ctx
        return context


class PageCreateUpdateMixin(object):

    template_name = 'dashboard/pages/update.html'
    model = FlatPage
    form_class = PageUpdateForm
    context_object_name = 'page'

    def get_success_url(self):
        msg = render_to_string('oscar/dashboard/pages/messages/saved.html',
                               {'page': self.object})
        messages.success(self.request, msg, extra_tags='safe noicon')
        return reverse('dashboard:page-list')

    def form_valid(self, form):
        # Ensure saved page is added to the current site
        # 确保已保存的页面已添加到当前站点
        page = form.save()
        if not page.sites.exists():
            page.sites.add(Site.objects.get_current())
        self.object = page
        return HttpResponseRedirect(self.get_success_url())


# 页面创建视图
class PageCreateView(PageCreateUpdateMixin, generic.CreateView):

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = _('Create New Page')
        return ctx

    def form_valid(self, form):
        """
        Store new flatpage from form data.
        Additionally, if URL is left blank, a slugified
        version of the title will be used as URL after checking
        if it is valid.
        从表单数据存储新的flatpage。 此外，如果URL留空，则在检查
        标题是否有效后，将使用标题的嵌入版本作为URL。
        """
        # if no URL is specified, generate from title
        # 如果未指定URL，则从title生成
        page = form.save(commit=False)

        if not page.url:
            page.url = '/%s/' % slugify(page.title)

        try:
            URLDoesNotExistValidator()(page.url)
        except ValidationError:
            pass
        else:
            return super().form_valid(form)

        ctx = self.get_context_data()
        ctx['form'] = form
        return self.render_to_response(ctx)


# 页面更新视图
class PageUpdateView(PageCreateUpdateMixin, generic.UpdateView):
    """
    View for updating flatpages from the dashboard.
    查看从仪表板更新flatpages。
    """
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = self.object.title
        return ctx


# 页面删除视图
class PageDeleteView(generic.DeleteView):
    template_name = 'dashboard/pages/delete.html'
    model = FlatPage

    def get_success_url(self):
        messages.success(
            self.request, _("Deleted page '%s'") % self.object.title)
        return reverse('dashboard:page-list')
