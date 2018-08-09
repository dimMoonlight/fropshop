import warnings

from django.contrib import messages
from django.core.paginator import InvalidPage
from django.http import Http404, HttpResponsePermanentRedirect
from django.shortcuts import get_object_or_404, redirect
from django.utils.http import urlquote
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView, TemplateView

from oscar.apps.catalogue.signals import product_viewed
from oscar.core.loading import get_class, get_model

Product = get_model('catalogue', 'product')
Category = get_model('catalogue', 'category')
ProductAlert = get_model('customer', 'ProductAlert')
ProductAlertForm = get_class('customer.forms', 'ProductAlertForm')
get_product_search_handler_class = get_class(
    'catalogue.search_handlers', 'get_product_search_handler_class')


# 产品细节视图
class ProductDetailView(DetailView):
    context_object_name = 'product'
    model = Product
    view_signal = product_viewed
    template_folder = "catalogue"

    # Whether to redirect to the URL with the right path
    # 是否使用正确的路径重定向到URL
    enforce_paths = True

    # Whether to redirect child products to their parent's URL
    # 是否将子产品重定向到其父级URL
    enforce_parent = True

    def get(self, request, **kwargs):
        """
        Ensures that the correct URL is used before rendering a response
        确保在呈现响应之前使用正确的URL
        """
        self.object = product = self.get_object()

        redirect = self.redirect_if_necessary(request.path, product)
        if redirect is not None:
            return redirect

        response = super().get(request, **kwargs)
        self.send_signal(request, response, product)
        return response

    # 得到对象
    def get_object(self, queryset=None):
        # Check if self.object is already set to prevent unnecessary DB calls
        # 检查是否已设置self.object以防止不必要的DB调用
        if hasattr(self, 'object'):
            return self.object
        else:
            return super().get_object(queryset)

    # 必要时重定向
    def redirect_if_necessary(self, current_path, product):
        if self.enforce_parent and product.is_child:
            return HttpResponsePermanentRedirect(
                product.parent.get_absolute_url())

        if self.enforce_paths:
            expected_path = product.get_absolute_url()
            if expected_path != urlquote(current_path):
                return HttpResponsePermanentRedirect(expected_path)

    # 获取上下文数据
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['alert_form'] = self.get_alert_form()
        ctx['has_active_alert'] = self.get_alert_status()
        return ctx

    # 获得警报状态
    def get_alert_status(self):
        # Check if this user already have an alert for this product
        # 检查此用户是否已收到此产品的警报
        has_alert = False
        if self.request.user.is_authenticated:
            alerts = ProductAlert.objects.filter(
                product=self.object, user=self.request.user,
                status=ProductAlert.ACTIVE)
            has_alert = alerts.exists()
        return has_alert

    # 得到提醒表格
    def get_alert_form(self):
        return ProductAlertForm(
            user=self.request.user, product=self.object)

    # 发送信号
    def send_signal(self, request, response, product):
        self.view_signal.send(
            sender=self, product=product, user=request.user, request=request,
            response=response)

    # 获取模板名称
    def get_template_names(self):
        """
        Return a list of possible templates.

        If an overriding class sets a template name, we use that. Otherwise,
        we try 2 options before defaulting to catalogue/detail.html:
            1). detail-for-upc-<upc>.html
            2). detail-for-class-<classname>.html

        This allows alternative templates to be provided for a per-product
        and a per-item-class basis.

        返回可能的模板列表。
        如果覆盖类设置模板名称，我们使用它。 除此之外，
        我们在默认为catalog / detail.html之前尝试2个选项：
            1). detail-for-upc-<upc>.html
            2). detail-for-class-<classname>.html
        这允许为每个产品和每个项目类提供替代模板。
        """
        if self.template_name:
            return [self.template_name]

        return [
            '%s/detail-for-upc-%s.html' % (
                self.template_folder, self.object.upc),
            '%s/detail-for-class-%s.html' % (
                self.template_folder, self.object.get_product_class().slug),
            '%s/detail.html' % (self.template_folder)]


# 目录视图
class CatalogueView(TemplateView):
    """
    Browse all products in the catalogue
    浏览目录中的所有产品
    """
    context_object_name = "products"
    template_name = 'catalogue/browse.html'

    def get(self, request, *args, **kwargs):
        try:
            self.search_handler = self.get_search_handler(
                self.request.GET, request.get_full_path(), [])
        except InvalidPage:
            # Redirect to page one.
            # 重定向到第一页。
            messages.error(request, _('The given page number was invalid.'))
            # 给定的页码无效。
            return redirect('catalogue:index')
        return super().get(request, *args, **kwargs)

    # 得到搜索处理程序
    def get_search_handler(self, *args, **kwargs):
        return get_product_search_handler_class()(*args, **kwargs)

    # 获取上下文数据
    def get_context_data(self, **kwargs):
        ctx = {}
        ctx['summary'] = _("All products")
        search_context = self.search_handler.get_search_context_data(
            self.context_object_name)
        ctx.update(search_context)
        return ctx


# 产品类别视图
class ProductCategoryView(TemplateView):
    """
    Browse products in a given category
    浏览给定类别中的产品
    """
    context_object_name = "products"
    template_name = 'catalogue/category.html'
    enforce_paths = True

    def get(self, request, *args, **kwargs):
        # Fetch the category; return 404 or redirect as needed
        # 获取类别; 根据需要返回404或重定向
        self.category = self.get_category()
        potential_redirect = self.redirect_if_necessary(
            request.path, self.category)
        if potential_redirect is not None:
            return potential_redirect

        try:
            self.search_handler = self.get_search_handler(
                request.GET, request.get_full_path(), self.get_categories())
        except InvalidPage:
            messages.error(request, _('The given page number was invalid.'))
            # 给定的页码无效。
            return redirect(self.category.get_absolute_url())

        return super().get(request, *args, **kwargs)

    # 得到类别
    def get_category(self):
        if 'pk' in self.kwargs:
            # Usual way to reach a category page. We just look at the primary
            # key, which is easy on the database. If the slug changed, get()
            # will redirect appropriately.
            # WARNING: Category.get_absolute_url needs to look up it's parents
            # to compute the URL. As this is slightly expensive, Oscar's
            # default implementation caches the method. That's pretty safe
            # as ProductCategoryView does the lookup by primary key, which
            # will work even if the cache is stale. But if you override this
            # logic, consider if that still holds true.
            # 通常的方式来达到类别页面。 我们只看一下主键，它在数据库上很容易。
            # 如果slug改变了，get（）将适当地重定向。
            # 警告：
            # Category.get_absolute_url需要查找它的父级来计算URL。
            # 由于这稍微昂贵，Oscar的默认实现缓存了该方法。 这是非常安全的，
            # 因为ProductCategoryView通过主键进行查找，即使缓存过时也可以工作。
            # 但如果你覆盖这个逻辑，考虑是否仍然适用。
            return get_object_or_404(Category, pk=self.kwargs['pk'])
        elif 'category_slug' in self.kwargs:
            # DEPRECATED. TODO: Remove in Oscar 1.2.
            # For SEO and legacy reasons, we allow chopping off the primary
            # key from the URL. In that case, we have the target category slug
            # and it's ancestors' slugs concatenated together.
            # To save on queries, we pick the last slug, look up all matching
            # categories and only then compare.
            # Note that currently we enforce uniqueness of slugs, but as that
            # might feasibly change soon, it makes sense to be forgiving here.
            # 弃用 删除Oscar 1.2版本。
            # 对于SEO和遗留原因，我们允许从URL中删除主键。 在这种情况下，
            # 我们有目标类别slug和它的祖先的slu together连接在一起。
            # 为了节省查询，我们选择最后一个slug，查找所有匹配的类别，然后才进行比较。
            # 请注意，目前我们强制执行slug的唯一性，但由于这可能很快就会
            # 发生变化，因此在这里宽容是有意义的。
            concatenated_slugs = self.kwargs['category_slug']
            slugs = concatenated_slugs.split(Category._slug_separator)
            try:
                last_slug = slugs[-1]
            except IndexError:
                raise Http404
            else:
                for category in Category.objects.filter(slug=last_slug):
                    if category.full_slug == concatenated_slugs:
                        # 不推荐使用不使用主键的类别将在Oscar 1.2中删除
                        message = (
                            "Accessing categories without a primary key"
                            " is deprecated will be removed in Oscar 1.2.")
                        warnings.warn(message, DeprecationWarning)

                        return category

        raise Http404

    def redirect_if_necessary(self, current_path, category):
        if self.enforce_paths:
            # Categories are fetched by primary key to allow slug changes.
            # If the slug has changed, issue a redirect.
            # 按主键提取类别以允许段塞更改。 如果slug已更改，请发出重定向。
            expected_path = category.get_absolute_url()
            if expected_path != urlquote(current_path):
                return HttpResponsePermanentRedirect(expected_path)

    # 得到搜索处理程序
    def get_search_handler(self, *args, **kwargs):
        return get_product_search_handler_class()(*args, **kwargs)

    # 得到类别
    def get_categories(self):
        """
        Return a list of the current category and its ancestors
        返回当前类别及其祖先的列表
        """
        return self.category.get_descendants_and_self()

    # 获取上下文数据
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['category'] = self.category
        search_context = self.search_handler.get_search_context_data(
            self.context_object_name)
        context.update(search_context)
        return context
