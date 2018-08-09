from django import http
from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _
from django.views import generic

from oscar.apps.customer.alerts import utils
from oscar.core.loading import get_class, get_model

Product = get_model('catalogue', 'Product')
ProductAlert = get_model('customer', 'ProductAlert')
PageTitleMixin = get_class('customer.mixins', 'PageTitleMixin')
ProductAlertForm = get_class('customer.forms', 'ProductAlertForm')


# 产品警报列表视图
class ProductAlertListView(PageTitleMixin, generic.ListView):
    model = ProductAlert
    template_name = 'customer/alerts/alert_list.html'
    context_object_name = 'alerts'
    page_title = _('Product Alerts')
    active_tab = 'alerts'

    def get_queryset(self):
        return ProductAlert.objects.select_related().filter(
            user=self.request.user,
            date_closed=None,
        )


# 产品快讯创建视图
class ProductAlertCreateView(generic.CreateView):
    """
    View to create a new product alert based on a registered user
    or an email address provided by an anonymous user.
    查看以基于注册用户或匿名用户提供的电子邮件地址创建新产品警报。
    """
    model = ProductAlert
    form_class = ProductAlertForm
    template_name = 'customer/alerts/form.html'

    # 获取上下文数据
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['product'] = self.product
        ctx['alert_form'] = ctx.pop('form')
        return ctx

    def get(self, request, *args, **kwargs):
        product = get_object_or_404(Product, pk=self.kwargs['pk'])
        return http.HttpResponseRedirect(product.get_absolute_url())

    def post(self, request, *args, **kwargs):
        self.product = get_object_or_404(Product, pk=self.kwargs['pk'])
        return super().post(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        kwargs['product'] = self.product
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.object.is_anonymous:
            utils.send_alert_confirmation(self.object)
        return response

    def get_success_url(self):
        if self.object.user:
            msg = _("An alert has been created")
        else:
            msg = _("A confirmation email has been sent to %s") \
                % self.object.email
        messages.success(self.request, msg)
        return self.object.product.get_absolute_url()


# 产品警报确认视图
class ProductAlertConfirmView(generic.RedirectView):
    permanent = False

    def get(self, request, *args, **kwargs):
        self.alert = get_object_or_404(ProductAlert, key=kwargs['key'])
        self.update_alert()
        return super().get(request, *args, **kwargs)

    def update_alert(self):
        if self.alert.can_be_confirmed:
            self.alert.confirm()
            messages.success(self.request, _("Your stock alert is now active"))
        else:
            messages.error(self.request, _("Your stock alert cannot be"
                                           " confirmed"))

    def get_redirect_url(self, **kwargs):
        return self.alert.product.get_absolute_url()


# 产品警报取消查看
class ProductAlertCancelView(generic.RedirectView):
    """
    This function allows canceling alerts by supplying the key (used for
    anonymously created alerts) or the pk (used for alerts created by a
    authenticated user).

    Specifying the redirect url is possible by supplying a 'next' GET
    parameter.  It defaults to showing the associated product page.

    此功能允许通过提供密钥（用于匿名创建的警报）或pk（用于由经过身份验证的
    用户创建的警报）来取消警报。

    通过提供“下一个”GET参数，可以指定重定向URL。 它默认显示关联的产品页面。
    """
    permanent = False

    def get(self, request, *args, **kwargs):
        if 'key' in kwargs:
            self.alert = get_object_or_404(ProductAlert, key=kwargs['key'])
        elif 'pk' in kwargs and request.user.is_authenticated:
            self.alert = get_object_or_404(ProductAlert,
                                           user=self.request.user,
                                           pk=kwargs['pk'])
        else:
            raise Http404
        self.update_alert()
        return super().get(request, *args, **kwargs)

    # 更新提醒
    def update_alert(self):
        if self.alert.can_be_cancelled:
            self.alert.cancel()
            messages.success(self.request, _("Your stock alert has been"
                                             " cancelled"))
        else:
            messages.error(self.request, _("Your stock alert cannot be"
                                           " cancelled"))

    def get_redirect_url(self, **kwargs):
        return self.request.GET.get('next',
                                    self.alert.product.get_absolute_url())
