from django import http
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.sites.shortcuts import get_current_site
from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views import generic

from oscar.apps.customer.utils import get_password_reset_url
from oscar.core.compat import get_user_model
from oscar.core.loading import (
    get_class, get_classes, get_model, get_profile_class)
from oscar.core.utils import safe_referrer
from oscar.views.generic import PostActionMixin

from . import signals

PageTitleMixin, RegisterUserMixin = get_classes(
    'customer.mixins', ['PageTitleMixin', 'RegisterUserMixin'])
Dispatcher = get_class('customer.utils', 'Dispatcher')
EmailAuthenticationForm, EmailUserCreationForm, OrderSearchForm = get_classes(
    'customer.forms', ['EmailAuthenticationForm', 'EmailUserCreationForm',
                       'OrderSearchForm'])
ProfileForm, ConfirmPasswordForm = get_classes(
    'customer.forms', ['ProfileForm', 'ConfirmPasswordForm'])
UserAddressForm = get_class('address.forms', 'UserAddressForm')
Order = get_model('order', 'Order')
Line = get_model('basket', 'Line')
Basket = get_model('basket', 'Basket')
UserAddress = get_model('address', 'UserAddress')
Email = get_model('customer', 'Email')
ProductAlert = get_model('customer', 'ProductAlert')
CommunicationEventType = get_model('customer', 'CommunicationEventType')

User = get_user_model()


# =======
# Account 账户
# =======


# 帐户汇总视图
class AccountSummaryView(generic.RedirectView):
    """
    View that exists for legacy reasons and customisability. It commonly gets
    called when the user clicks on "Account" in the navbar.

    Oscar defaults to just redirecting to the profile summary page (and
    that redirect can be configured via OSCAR_ACCOUNT_REDIRECT_URL), but
    it's also likely you want to display an 'account overview' page or
    such like. The presence of this view allows just that, without
    having to change a lot of templates.

    由于遗留原因和可定制性而存在的查看。 当用户点击导航栏中的“帐户”时，
    通常会调用它。

    Oscar默认只是重定向到配置文件摘要页面（并且可以通过OSCAR_ACCOUNT_REDIRECT_URL配置
    该重定向），但您也可能希望显示“帐户概述”页面等。 此视图的存在允许这
    样做，而无需更改大量模板。
    """
    pattern_name = settings.OSCAR_ACCOUNTS_REDIRECT_URL
    permanent = False


# 帐户注册视图
class AccountRegistrationView(RegisterUserMixin, generic.FormView):
    form_class = EmailUserCreationForm
    template_name = 'customer/registration.html'
    redirect_field_name = 'next'

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect(settings.LOGIN_REDIRECT_URL)
        return super().get(
            request, *args, **kwargs)

    # 获得登录重定向
    def get_logged_in_redirect(self):
        return reverse('customer:summary')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['initial'] = {
            'email': self.request.GET.get('email', ''),
            'redirect_url': self.request.GET.get(self.redirect_field_name, '')
        }
        kwargs['host'] = self.request.get_host()
        return kwargs

    def get_context_data(self, *args, **kwargs):
        ctx = super().get_context_data(
            *args, **kwargs)
        ctx['cancel_url'] = safe_referrer(self.request, '')
        return ctx

    def form_valid(self, form):
        self.register_user(form)
        return redirect(form.cleaned_data['redirect_url'])


# 帐户视图
class AccountAuthView(RegisterUserMixin, generic.TemplateView):
    """
    This is actually a slightly odd double form view that allows a customer to
    either login or register.
    这实际上是一个稍微奇怪的双视图，允许客户登录或注册。
    """
    template_name = 'customer/login_registration.html'
    login_prefix, registration_prefix = 'login', 'registration'
    login_form_class = EmailAuthenticationForm
    registration_form_class = EmailUserCreationForm
    redirect_field_name = 'next'

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect(settings.LOGIN_REDIRECT_URL)
        return super().get(
            request, *args, **kwargs)

    def get_context_data(self, *args, **kwargs):
        ctx = super().get_context_data(*args, **kwargs)
        if 'login_form' not in kwargs:
            ctx['login_form'] = self.get_login_form()
        if 'registration_form' not in kwargs:
            ctx['registration_form'] = self.get_registration_form()
        return ctx

    def post(self, request, *args, **kwargs):
        # Use the name of the submit button to determine which form to validate
        # 使用提交按钮的名称来确定要验证的表单
        if 'login_submit' in request.POST:
            return self.validate_login_form()
        elif 'registration_submit' in request.POST:
            return self.validate_registration_form()
        return http.HttpResponseBadRequest()

    # LOGIN 登录

    def get_login_form(self, bind_data=False):
        return self.login_form_class(
            **self.get_login_form_kwargs(bind_data))

    def get_login_form_kwargs(self, bind_data=False):
        kwargs = {}
        kwargs['host'] = self.request.get_host()
        kwargs['prefix'] = self.login_prefix
        kwargs['initial'] = {
            'redirect_url': self.request.GET.get(self.redirect_field_name, ''),
        }
        if bind_data and self.request.method in ('POST', 'PUT'):
            kwargs.update({
                'data': self.request.POST,
                'files': self.request.FILES,
            })
        return kwargs

    def validate_login_form(self):
        form = self.get_login_form(bind_data=True)
        if form.is_valid():
            user = form.get_user()

            # Grab a reference to the session ID before logging in
            # 登录前获取对会话ID的引用
            old_session_key = self.request.session.session_key

            auth_login(self.request, form.get_user())

            # Raise signal robustly (we don't want exceptions to crash the
            # request handling). We use a custom signal as we want to track the
            # session key before calling login (which cycles the session ID).
            # 有力地提高信号（我们不希望异常崩溃请求处理）。在调用Login
            # （循环会话ID）之前，我们使用自定义信号来跟踪会话密钥。
            signals.user_logged_in.send_robust(
                sender=self, request=self.request, user=user,
                old_session_key=old_session_key)

            msg = self.get_login_success_message(form)
            if msg:
                messages.success(self.request, msg)

            return redirect(self.get_login_success_url(form))

        ctx = self.get_context_data(login_form=form)
        return self.render_to_response(ctx)

    def get_login_success_message(self, form):
        return _("Welcome back")

    def get_login_success_url(self, form):
        redirect_url = form.cleaned_data['redirect_url']
        if redirect_url:
            return redirect_url

        # Redirect staff members to dashboard as that's the most likely place
        # they'll want to visit if they're logging in.
        # 将工作人员重定向到仪表板，因为这是他们登录时最有可能访问的地方。
        if self.request.user.is_staff:
            return reverse('dashboard:index')

        return settings.LOGIN_REDIRECT_URL

    # REGISTRATION 注册

    def get_registration_form(self, bind_data=False):
        return self.registration_form_class(
            **self.get_registration_form_kwargs(bind_data))

    def get_registration_form_kwargs(self, bind_data=False):
        kwargs = {}
        kwargs['host'] = self.request.get_host()
        kwargs['prefix'] = self.registration_prefix
        kwargs['initial'] = {
            'redirect_url': self.request.GET.get(self.redirect_field_name, ''),
        }
        if bind_data and self.request.method in ('POST', 'PUT'):
            kwargs.update({
                'data': self.request.POST,
                'files': self.request.FILES,
            })
        return kwargs

    def validate_registration_form(self):
        form = self.get_registration_form(bind_data=True)
        if form.is_valid():
            self.register_user(form)

            msg = self.get_registration_success_message(form)
            messages.success(self.request, msg)

            return redirect(self.get_registration_success_url(form))

        ctx = self.get_context_data(registration_form=form)
        return self.render_to_response(ctx)

    def get_registration_success_message(self, form):
        return _("Thanks for registering!")

    def get_registration_success_url(self, form):
        redirect_url = form.cleaned_data['redirect_url']
        if redirect_url:
            return redirect_url

        return settings.LOGIN_REDIRECT_URL


# 退出、注销视图
class LogoutView(generic.RedirectView):
    url = settings.OSCAR_HOMEPAGE
    permanent = False

    def get(self, request, *args, **kwargs):
        auth_logout(request)
        response = super().get(request, *args, **kwargs)

        for cookie in settings.OSCAR_COOKIES_DELETE_ON_LOGOUT:
            response.delete_cookie(cookie)

        return response


# =============
# Profile 配置文件
# =============


class ProfileView(PageTitleMixin, generic.TemplateView):
    template_name = 'customer/profile/profile.html'
    page_title = _('Profile')
    active_tab = 'profile'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['profile_fields'] = self.get_profile_fields(self.request.user)
        return ctx

    def get_profile_fields(self, user):
        field_data = []

        # Check for custom user model
        # 检查自定义用户模型
        for field_name in User._meta.additional_fields:
            field_data.append(
                self.get_model_field_data(user, field_name))

        # Check for profile class
        # 检查配置文件类
        profile_class = get_profile_class()
        if profile_class:
            try:
                profile = profile_class.objects.get(user=user)
            except ObjectDoesNotExist:
                profile = profile_class(user=user)

            field_names = [f.name for f in profile._meta.local_fields]
            for field_name in field_names:
                if field_name in ('user', 'id'):
                    continue
                field_data.append(
                    self.get_model_field_data(profile, field_name))

        return field_data

    def get_model_field_data(self, model_class, field_name):
        """
        Extract the verbose name and value for a model's field value
        提取模型的字段值的详细名称和值
        """
        field = model_class._meta.get_field(field_name)
        if field.choices:
            value = getattr(model_class, 'get_%s_display' % field_name)()
        else:
            value = getattr(model_class, field_name)
        return {
            'name': getattr(field, 'verbose_name'),
            'value': value,
        }


# 配置文件更新视图
class ProfileUpdateView(PageTitleMixin, generic.FormView):
    form_class = ProfileForm
    template_name = 'customer/profile/profile_form.html'
    communication_type_code = 'EMAIL_CHANGED'
    page_title = _('Edit Profile')
    active_tab = 'profile'
    success_url = reverse_lazy('customer:profile-view')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        # Grab current user instance before we save form.  We may need this to
        # send a warning email if the email address is changed.
        # 在保存表单之前抓取当前用户实例。 如果更改了电子邮件地址，我们
        # 可能需要此信息才能发送警告电子邮件。
        try:
            old_user = User.objects.get(id=self.request.user.id)
        except User.DoesNotExist:
            old_user = None

        form.save()

        # We have to look up the email address from the form's
        # cleaned data because the object created by form.save() can
        # either be a user or profile instance depending whether a profile
        # class has been specified by the AUTH_PROFILE_MODULE setting.
        # 我们必须从表单的清理数据中查找电子邮件地址，因为form.save（）
        # 创建的对象可以是用户或配置文件实例，具体取决于AUTH_PROFILE_MODULE设置
        # 是否指定了配置文件类。
        new_email = form.cleaned_data.get('email')
        if new_email and old_user and new_email != old_user.email:
            # Email address has changed - send a confirmation email to the old
            # address including a password reset link in case this is a
            # suspicious change.
            # 电子邮件地址已更改 - 如果这是可疑更改，请向旧地址发送确认电子
            # 邮件，包括密码重置链接。
            ctx = {
                'user': self.request.user,
                'site': get_current_site(self.request),
                'reset_url': get_password_reset_url(old_user),
                'new_email': new_email,
            }
            msgs = CommunicationEventType.objects.get_and_render(
                code=self.communication_type_code, context=ctx)
            Dispatcher().dispatch_user_messages(old_user, msgs)

        messages.success(self.request, _("Profile updated"))
        return redirect(self.get_success_url())


# 配置文件删除视图
class ProfileDeleteView(PageTitleMixin, generic.FormView):
    form_class = ConfirmPasswordForm
    template_name = 'customer/profile/profile_delete.html'
    page_title = _('Delete profile')
    active_tab = 'profile'
    success_url = settings.OSCAR_HOMEPAGE

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        self.request.user.delete()
        messages.success(
            self.request,
            _("Your profile has now been deleted. Thanks for using the site."))
        return redirect(self.get_success_url())


# 更改密码视图
class ChangePasswordView(PageTitleMixin, generic.FormView):
    form_class = PasswordChangeForm
    template_name = 'customer/profile/change_password_form.html'
    communication_type_code = 'PASSWORD_CHANGED'
    page_title = _('Change Password')
    active_tab = 'profile'
    success_url = reverse_lazy('customer:profile-view')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        form.save()
        update_session_auth_hash(self.request, self.request.user)
        messages.success(self.request, _("Password updated"))

        ctx = {
            'user': self.request.user,
            'site': get_current_site(self.request),
            'reset_url': get_password_reset_url(self.request.user),
        }
        msgs = CommunicationEventType.objects.get_and_render(
            code=self.communication_type_code, context=ctx)
        Dispatcher().dispatch_user_messages(self.request.user, msgs)

        return redirect(self.get_success_url())


# =============
# Email history 电子邮件历史
# =============

class EmailHistoryView(PageTitleMixin, generic.ListView):
    context_object_name = "emails"
    template_name = 'customer/email/email_list.html'
    paginate_by = settings.OSCAR_EMAILS_PER_PAGE
    page_title = _('Email History')
    active_tab = 'emails'

    def get_queryset(self):
        return Email._default_manager.filter(user=self.request.user)


class EmailDetailView(PageTitleMixin, generic.DetailView):
    """Customer email 客户电子邮件"""
    template_name = "customer/email/email_detail.html"
    context_object_name = 'email'
    active_tab = 'emails'

    def get_object(self, queryset=None):
        return get_object_or_404(Email, user=self.request.user,
                                 id=self.kwargs['email_id'])

    def get_page_title(self):
        """
        Append email subject to page title
        根据页面标题附加电子邮件
        """
        return '%s: %s' % (_('Email'), self.object.subject)


# =============
# Order history 订单历史
# =============

# 订单历史视图
class OrderHistoryView(PageTitleMixin, generic.ListView):
    """
    Customer order history
    """
    context_object_name = "orders"
    template_name = 'customer/order/order_list.html'
    paginate_by = settings.OSCAR_ORDERS_PER_PAGE
    model = Order
    form_class = OrderSearchForm
    page_title = _('Order History')
    active_tab = 'orders'

    def get(self, request, *args, **kwargs):
        if 'date_from' in request.GET:
            self.form = self.form_class(self.request.GET)
            if not self.form.is_valid():
                self.object_list = self.get_queryset()
                ctx = self.get_context_data(object_list=self.object_list)
                return self.render_to_response(ctx)
            data = self.form.cleaned_data

            # If the user has just entered an order number, try and look it up
            # and redirect immediately to the order detail page.
            # 如果用户刚刚输入了订单号，请尝试查找并立即重定向到订单详细信息页面。
            if data['order_number'] and not (data['date_to'] or
                                             data['date_from']):
                try:
                    order = Order.objects.get(
                        number=data['order_number'], user=self.request.user)
                except Order.DoesNotExist:
                    pass
                else:
                    return redirect(
                        'customer:order', order_number=order.number)
        else:
            self.form = self.form_class()
        return super().get(request, *args, **kwargs)

    # 获取查询集
    def get_queryset(self):
        qs = self.model._default_manager.filter(user=self.request.user)
        if self.form.is_bound and self.form.is_valid():
            qs = qs.filter(**self.form.get_filters())
        return qs

    # 获取上下文数据
    def get_context_data(self, *args, **kwargs):
        ctx = super().get_context_data(*args, **kwargs)
        ctx['form'] = self.form
        return ctx


# 订单明细视图
class OrderDetailView(PageTitleMixin, PostActionMixin, generic.DetailView):
    model = Order
    active_tab = 'orders'

    def get_template_names(self):
        return ["customer/order/order_detail.html"]

    def get_page_title(self):
        """
        Order number as page title
        订单号作为页面标题
        """
        return '%s #%s' % (_('Order'), self.object.number)

    def get_object(self, queryset=None):
        return get_object_or_404(self.model, user=self.request.user,
                                 number=self.kwargs['order_number'])

    def do_reorder(self, order):  # noqa (too complex (10))
        """
        'Re-order' a previous order.

        This puts the contents of the previous order into your basket

        '重新订购'之前的订单。
        这会将先前订单的内容放入您的购物篮中
        """
        # Collect lines to be added to the basket and any warnings for lines
        # that are no longer available.
        # 收集要添加到购物篮的行以及不再可用的行的任何警告。
        basket = self.request.basket
        lines_to_add = []
        warnings = []
        for line in order.lines.all():
            is_available, reason = line.is_available_to_reorder(
                basket, self.request.strategy)
            if is_available:
                lines_to_add.append(line)
            else:
                warnings.append(reason)

        # Check whether the number of items in the basket won't exceed the
        # maximum.
        # 检查购物篮中的物品数量是否不超过最大值。
        total_quantity = sum([line.quantity for line in lines_to_add])
        is_quantity_allowed, reason = basket.is_quantity_allowed(
            total_quantity)
        if not is_quantity_allowed:
            messages.warning(self.request, reason)
            self.response = redirect('customer:order-list')
            return

        # Add any warnings
        # 添加一些警告
        for warning in warnings:
            messages.warning(self.request, warning)

        for line in lines_to_add:
            options = []
            for attribute in line.attributes.all():
                if attribute.option:
                    options.append({
                        'option': attribute.option,
                        'value': attribute.value})
            basket.add_product(line.product, line.quantity, options)

        if len(lines_to_add) > 0:
            self.response = redirect('basket:summary')
            messages.info(
                self.request,
                _("All available lines from order %(number)s "
                  "have been added to your basket") % {'number': order.number})
        else:
            self.response = redirect('customer:order-list')
            messages.warning(
                self.request,
                _("It is not possible to re-order order %(number)s "
                  "as none of its lines are available to purchase") %
                {'number': order.number})


# 订单行视图
class OrderLineView(PostActionMixin, generic.DetailView):
    """Customer order line 客户订单行"""

    def get_object(self, queryset=None):
        order = get_object_or_404(Order, user=self.request.user,
                                  number=self.kwargs['order_number'])
        return order.lines.get(id=self.kwargs['line_id'])

    def do_reorder(self, line):
        self.response = redirect('customer:order', self.kwargs['order_number'])
        basket = self.request.basket

        line_available_to_reorder, reason = line.is_available_to_reorder(
            basket, self.request.strategy)

        if not line_available_to_reorder:
            messages.warning(self.request, reason)
            return

        # We need to pass response to the get_or_create... method
        # as a new basket might need to be created
        # 我们需要将响应传递给get_or_create ...方法，因为可能需要创建一个新的购物篮
        self.response = redirect('basket:summary')

        # Convert line attributes into basket options
        # 将行属性转换为购物篮选项
        options = []
        for attribute in line.attributes.all():
            if attribute.option:
                options.append({'option': attribute.option,
                                'value': attribute.value})
        basket.add_product(line.product, line.quantity, options)

        if line.quantity > 1:
            msg = _("%(qty)d copies of '%(product)s' have been added to your"
                    " basket") % {
                'qty': line.quantity, 'product': line.product}
        else:
            msg = _("'%s' has been added to your basket") % line.product

        messages.info(self.request, msg)


# 匿名订单详细信息视图
class AnonymousOrderDetailView(generic.DetailView):
    model = Order
    template_name = "customer/anon_order.html"

    def get_object(self, queryset=None):
        # Check URL hash matches that for order to prevent spoof attacks
        # 检查URL散列是否匹配以防止欺骗攻击
        order = get_object_or_404(self.model, user=None,
                                  number=self.kwargs['order_number'])
        if not order.check_verification_hash(self.kwargs['hash']):
            raise http.Http404()
        return order


# ------------
# Address book 地址簿
# ------------

# 地址列表视图
class AddressListView(PageTitleMixin, generic.ListView):
    """Customer address book 客户通讯录"""
    context_object_name = "addresses"
    template_name = 'customer/address/address_list.html'
    paginate_by = settings.OSCAR_ADDRESSES_PER_PAGE
    active_tab = 'addresses'
    page_title = _('Address Book')

    def get_queryset(self):
        """Return customer's addresses 返回客户的地址"""
        return UserAddress._default_manager.filter(user=self.request.user)


# 地址创建视图
class AddressCreateView(PageTitleMixin, generic.CreateView):
    form_class = UserAddressForm
    model = UserAddress
    template_name = 'customer/address/address_form.html'
    active_tab = 'addresses'
    page_title = _('Add a new address')
    success_url = reverse_lazy('customer:address-list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = _('Add a new address')
        return ctx

    def get_success_url(self):
        messages.success(self.request,
                         _("Address '%s' created") % self.object.summary)
        return super().get_success_url()


# 地址更新视图
class AddressUpdateView(PageTitleMixin, generic.UpdateView):
    form_class = UserAddressForm
    model = UserAddress
    template_name = 'customer/address/address_form.html'
    active_tab = 'addresses'
    page_title = _('Edit address')
    success_url = reverse_lazy('customer:address-list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = _('Edit address')
        return ctx

    def get_queryset(self):
        return self.request.user.addresses.all()

    def get_success_url(self):
        messages.success(self.request,
                         _("Address '%s' updated") % self.object.summary)
        return super().get_success_url()


# 地址删除视图
class AddressDeleteView(PageTitleMixin, generic.DeleteView):
    model = UserAddress
    template_name = "customer/address/address_delete.html"
    page_title = _('Delete address?')
    active_tab = 'addresses'
    context_object_name = 'address'
    success_url = reverse_lazy('customer:address-list')

    def get_queryset(self):
        return UserAddress._default_manager.filter(user=self.request.user)

    def get_success_url(self):
        messages.success(self.request,
                         _("Address '%s' deleted") % self.object.summary)
        return super().get_success_url()


# 地址变更状态视图
class AddressChangeStatusView(generic.RedirectView):
    """
    Sets an address as default_for_(billing|shipping)
    将地址设置为default_for_（结算|发货）
    """
    url = reverse_lazy('customer:address-list')
    permanent = False

    def get(self, request, pk=None, action=None, *args, **kwargs):
        address = get_object_or_404(UserAddress, user=self.request.user,
                                    pk=pk)
        #  We don't want the user to set an address as the default shipping
        #  address, though they should be able to set it as their billing
        #  address.
        # 我们不希望用户将地址设置为默认送货地址，但他们应该能够将其设置
        # 为帐单邮寄地址。
        if address.country.is_shipping_country:
            setattr(address, 'is_%s' % action, True)
        elif action == 'default_for_billing':
            setattr(address, 'is_default_for_billing', True)
        else:
            messages.error(request, _('We do not ship to this country'))
        address.save()
        return super().get(
            request, *args, **kwargs)
