import logging

from django import http
from django.contrib import messages
from django.contrib.auth import login
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.utils.http import urlquote
from django.utils.translation import gettext as _
from django.views import generic

from oscar.core.loading import get_class, get_classes, get_model

from . import signals

ShippingAddressForm, ShippingMethodForm, GatewayForm \
    = get_classes('checkout.forms', ['ShippingAddressForm', 'ShippingMethodForm', 'GatewayForm'])
OrderCreator = get_class('order.utils', 'OrderCreator')
UserAddressForm = get_class('address.forms', 'UserAddressForm')
Repository = get_class('shipping.repository', 'Repository')
AccountAuthView = get_class('customer.views', 'AccountAuthView')
RedirectRequired, UnableToTakePayment, PaymentError \
    = get_classes('payment.exceptions', ['RedirectRequired',
                                         'UnableToTakePayment',
                                         'PaymentError'])
UnableToPlaceOrder = get_class('order.exceptions', 'UnableToPlaceOrder')
OrderPlacementMixin = get_class('checkout.mixins', 'OrderPlacementMixin')
CheckoutSessionMixin = get_class('checkout.session', 'CheckoutSessionMixin')
NoShippingRequired = get_class('shipping.methods', 'NoShippingRequired')
Order = get_model('order', 'Order')
ShippingAddress = get_model('order', 'ShippingAddress')
CommunicationEvent = get_model('order', 'CommunicationEvent')
PaymentEventType = get_model('order', 'PaymentEventType')
PaymentEvent = get_model('order', 'PaymentEvent')
UserAddress = get_model('address', 'UserAddress')
Basket = get_model('basket', 'Basket')
Email = get_model('customer', 'Email')
Country = get_model('address', 'Country')
CommunicationEventType = get_model('customer', 'CommunicationEventType')

# Standard logger for checkout events
# 结帐活动的标准记录器
logger = logging.getLogger('oscar.checkout')


# 索引视图
class IndexView(CheckoutSessionMixin, generic.FormView):
    """
    First page of the checkout.  We prompt user to either sign in, or
    to proceed as a guest (where we still collect their email address).
    结帐的第一页。 我们提示用户登录，或以访客身份继续（我们仍会收集他们的
    电子邮件地址）。
    """
    template_name = 'checkout/gateway.html'
    form_class = GatewayForm
    success_url = reverse_lazy('checkout:shipping-address')
    pre_conditions = [
        'check_basket_is_not_empty',
        'check_basket_is_valid']

    def get(self, request, *args, **kwargs):
        # We redirect immediately to shipping address stage if the user is
        # signed in.
        # 如果用户已登录，我们会立即重定向到送货地址阶段。
        if request.user.is_authenticated:
            # We raise a signal to indicate that the user has entered the
            # checkout process so analytics tools can track this event.
            # 我们发出信号表示用户已进入结帐流程，因此分析工具可以跟踪此事件。
            signals.start_checkout.send_robust(
                sender=self, request=request)
            return self.get_success_response()
        return super().get(request, *args, **kwargs)

    # 得到表格kwargs
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        email = self.checkout_session.get_guest_email()
        if email:
            kwargs['initial'] = {
                'username': email,
            }
        return kwargs

    # 有效表格
    def form_valid(self, form):
        if form.is_guest_checkout() or form.is_new_account_checkout():
            email = form.cleaned_data['username']
            self.checkout_session.set_guest_email(email)

            # We raise a signal to indicate that the user has entered the
            # checkout process by specifying an email address.
            # 我们通过指定电子邮件地址发出信号以指示用户已进入结账流程。
            signals.start_checkout.send_robust(
                sender=self, request=self.request, email=email)

            if form.is_new_account_checkout():
                # 创建您的帐户，然后您将被重定向回结帐流程
                messages.info(
                    self.request,
                    _("Create your account and then you will be redirected "
                      "back to the checkout process"))
                self.success_url = "%s?next=%s&email=%s" % (
                    reverse('customer:register'),
                    reverse('checkout:shipping-address'),
                    urlquote(email)
                )
        else:
            user = form.get_user()
            login(self.request, user)

            # We raise a signal to indicate that the user has entered the
            # checkout process.
            # 我们发出一个信号表示用户已进入结账流程。
            signals.start_checkout.send_robust(
                sender=self, request=self.request)

        return redirect(self.get_success_url())

    def get_success_response(self):
        return redirect(self.get_success_url())


# ================
# SHIPPING ADDRESS
# 邮寄地址
# ================


# 送货地址视图
class ShippingAddressView(CheckoutSessionMixin, generic.FormView):
    """
    Determine the shipping address for the order.

    The default behaviour is to display a list of addresses from the users's
    address book, from which the user can choose one to be their shipping
    address.  They can add/edit/delete these USER addresses.  This address will
    be automatically converted into a SHIPPING address when the user checks
    out.

    Alternatively, the user can enter a SHIPPING address directly which will be
    saved in the session and later saved as ShippingAddress model when the
    order is successfully submitted.

    确定订单的送货地址。
    默认行为是显示用户地址簿中的地址列表，用户可以从中选择一个地址作为其送货地址。
    他们可以添加/编辑/删除这些用户地址。 当用户结账时，该地址将自动转换为
    SHIPPING地址。
    或者，用户可以直接输入SHIPPING地址，该地址将保存在会话中，并在成功提交订单
    后保存为ShippingAddress模型。
    """
    template_name = 'checkout/shipping_address.html'
    form_class = ShippingAddressForm
    success_url = reverse_lazy('checkout:shipping-method')
    pre_conditions = ['check_basket_is_not_empty',
                      'check_basket_is_valid',
                      'check_user_email_is_captured']
    skip_conditions = ['skip_unless_basket_requires_shipping']

    # 得到初始
    def get_initial(self):
        initial = self.checkout_session.new_shipping_address_fields()
        if initial:
            initial = initial.copy()
            # Convert the primary key stored in the session into a Country
            # instance
            # 将存储在会话中的主键转换为Country实例
            try:
                initial['country'] = Country.objects.get(
                    iso_3166_1_a2=initial.pop('country_id'))
            except Country.DoesNotExist:
                # Hmm, the previously selected Country no longer exists. We
                # ignore this.
                # 嗯，之前选择的国家不再存在。 我们忽略了这个。
                pass
        return initial

    # 获取上下文数据
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if self.request.user.is_authenticated:
            # Look up address book data
            # 查找地址簿数据
            ctx['addresses'] = self.get_available_addresses()
        return ctx

    # 获取可用的地址
    def get_available_addresses(self):
        # Include only addresses where the country is flagged as valid for
        # shipping. Also, use ordering to ensure the default address comes
        # first.
        # 仅包括国家/地区被标记为有效运送的地址。 此外，使用排序以确保首先出现
        # 默认地址。
        return self.request.user.addresses.filter(
            country__is_shipping_country=True).order_by(
            '-is_default_for_shipping')

    def post(self, request, *args, **kwargs):
        # Check if a shipping address was selected directly (eg no form was
        # filled in)
        # 检查是否直接选择了送货地址（例如，没有填写表格）
        if self.request.user.is_authenticated \
                and 'address_id' in self.request.POST:
            address = UserAddress._default_manager.get(
                pk=self.request.POST['address_id'], user=self.request.user)
            action = self.request.POST.get('action', None)
            if action == 'ship_to':
                # User has selected a previous address to ship to
                # 用户已选择要发送到的先前地址
                self.checkout_session.ship_to_user_address(address)
                return redirect(self.get_success_url())
            else:
                return http.HttpResponseBadRequest()
        else:
            return super().post(
                request, *args, **kwargs)

    # 表格有效
    def form_valid(self, form):
        # Store the address details in the session and redirect to next step
        # 将地址详细信息存储在会话中并重定向到下一步
        address_fields = dict(
            (k, v) for (k, v) in form.instance.__dict__.items()
            if not k.startswith('_'))
        self.checkout_session.ship_to_new_address(address_fields)
        return super().form_valid(form)


# 用户地址更新视图
class UserAddressUpdateView(CheckoutSessionMixin, generic.UpdateView):
    """
    Update a user address
    更新用户地址
    """
    template_name = 'checkout/user_address_form.html'
    form_class = UserAddressForm
    success_url = reverse_lazy('checkout:shipping-address')

    # 获取查询集
    def get_queryset(self):
        return self.request.user.addresses.all()

    # 得到表格kwargs
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_success_url(self):
        messages.info(self.request, _("Address saved"))
        return super().get_success_url()


# 用户地址删除视图
class UserAddressDeleteView(CheckoutSessionMixin, generic.DeleteView):
    """
    Delete an address from a user's address book.
    从用户的地址簿中删除地址。
    """
    template_name = 'checkout/user_address_delete.html'
    success_url = reverse_lazy('checkout:shipping-address')

    def get_queryset(self):
        return self.request.user.addresses.all()

    def get_success_url(self):
        messages.info(self.request, _("Address deleted"))
        return super().get_success_url()


# ===============
# Shipping method
# 邮寄方式
# ===============


# 送货方式查看
class ShippingMethodView(CheckoutSessionMixin, generic.FormView):
    """
    View for allowing a user to choose a shipping method.

    Shipping methods are largely domain-specific and so this view
    will commonly need to be subclassed and customised.

    The default behaviour is to load all the available shipping methods
    using the shipping Repository.  If there is only 1, then it is
    automatically selected.  Otherwise, a page is rendered where
    the user can choose the appropriate one.

    允许用户选择送货方式的视图。

    运输方法主要是特定于域的，因此通常需要对此视图进行子类化和自定义。

    默认行为是使用送货存储库加载所有可用的送货方法。 如果只有1，则自动选择。
    否则，将呈现页面，用户可以在其中选择适当的页面。
    """
    template_name = 'checkout/shipping_methods.html'
    form_class = ShippingMethodForm
    pre_conditions = ['check_basket_is_not_empty',
                      'check_basket_is_valid',
                      'check_user_email_is_captured']

    def post(self, request, *args, **kwargs):
        self._methods = self.get_available_shipping_methods()
        return super().post(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        # These pre-conditions can't easily be factored out into the normal
        # pre-conditions as they do more than run a test and then raise an
        # exception on failure.
        # 这些前提条件不容易被分解到正常的前提条件中，因为它们不仅仅运行测试，
        # 而且在失败时引发异常。

        # Check that shipping is required at all
        # 检查是否需要运输
        if not request.basket.is_shipping_required():
            # No shipping required - we store a special code to indicate so.
            # 无需送货 - 我们存储了一个特殊代码来表明。s
            self.checkout_session.use_shipping_method(
                NoShippingRequired().code)
            return self.get_success_response()

        # Check that shipping address has been completed
        # 检查送货地址是否已完成
        if not self.checkout_session.is_shipping_address_set():
            messages.error(request, _("Please choose a shipping address"))
            return redirect('checkout:shipping-address')

        # Save shipping methods as instance var as we need them both here
        # and when setting the context vars.
        # 将运输方法保存为实例var，因为我们在此处以及在设置上下文变量时都需要它们。
        self._methods = self.get_available_shipping_methods()
        if len(self._methods) == 0:
            # No shipping methods available for given address
            # 没有可用于指定地址的送货方式
            messages.warning(request, _(
                "Shipping is unavailable for your chosen address - please "
                "choose another"))
            # 您所选择的地址无法发货 - 请选择其他地址
            return redirect('checkout:shipping-address')
        elif len(self._methods) == 1:
            # Only one shipping method - set this and redirect onto the next
            # step
            # 只有一种送货方式 - 设置此方法并重定向到下一步
            self.checkout_session.use_shipping_method(self._methods[0].code)
            return self.get_success_response()

        # Must be more than one available shipping method, we present them to
        # the user to make a choice.
        # 必须是多种可用的送货方式，我们将它们呈现给用户做出选择。
        return super().get(request, *args, **kwargs)

    # 获取上下文数据
    def get_context_data(self, **kwargs):
        kwargs = super().get_context_data(**kwargs)
        kwargs['methods'] = self._methods
        return kwargs

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['methods'] = self._methods
        return kwargs

    # 获得可用的送货方式
    def get_available_shipping_methods(self):
        """
        Returns all applicable shipping method objects for a given basket.
        返回给定购物篮的所有适用的送货方法对象。
        """
        # Shipping methods can depend on the user, the contents of the basket
        # and the shipping address (so we pass all these things to the
        # repository).  I haven't come across a scenario that doesn't fit this
        # system.
        # 送货方式取决于用户，购物篮的内容和送货地址（因此我们将所有这些内容传递给存储库）。
        #  我没有遇到过不适合这个系统的场景。
        return Repository().get_shipping_methods(
            basket=self.request.basket, user=self.request.user,
            shipping_addr=self.get_shipping_address(self.request.basket),
            request=self.request)

    def form_valid(self, form):
        # Save the code for the chosen shipping method in the session
        # and continue to the next step.
        # 在会话中保存所选送货方法的代码，然后继续执行下一步。
        self.checkout_session.use_shipping_method(form.cleaned_data['method_code'])
        return self.get_success_response()

    def form_invalid(self, form):
        # 不允许使用您提交的送货方式
        messages.error(self.request, _("Your submitted shipping method is not"
                                       " permitted"))
        return super().form_invalid(form)

    def get_success_response(self):
        return redirect('checkout:payment-method')


# ==============
# Payment method
# 付款方法
# ==============


# 付款方式视图
class PaymentMethodView(CheckoutSessionMixin, generic.TemplateView):
    """
    View for a user to choose which payment method(s) they want to use.

    This would include setting allocations if payment is to be split
    between multiple sources. It's not the place for entering sensitive details
    like bankcard numbers though - that belongs on the payment details view.

    查看用户选择要使用的付款方式。
    这将包括在多个来源之间分配付款时设置分配。 它不是输入银行卡号等敏感细节
    的地方 - 属于付款详情视图。
    """
    pre_conditions = [
        'check_basket_is_not_empty',
        'check_basket_is_valid',
        'check_user_email_is_captured',
        'check_shipping_data_is_captured']
    skip_conditions = ['skip_unless_payment_is_required']

    def get(self, request, *args, **kwargs):
        # By default we redirect straight onto the payment details view. Shops
        # that require a choice of payment method may want to override this
        # method to implement their specific logic.
        # 默认情况下，我们会直接重定向到付款明细视图。 需要选择付款方式的商店
        # 可能希望覆盖此方法以实现其特定逻辑。
        return self.get_success_response()

    def get_success_response(self):
        return redirect('checkout:payment-details')


# ================
# Order submission
# 订单提交
# ================


# 付款详情查看
class PaymentDetailsView(OrderPlacementMixin, generic.TemplateView):
    """
    For taking the details of payment and creating the order.

    This view class is used by two separate URLs: 'payment-details' and
    'preview'. The `preview` class attribute is used to distinguish which is
    being used. Chronologically, `payment-details` (preview=False) comes before
    `preview` (preview=True).

    If sensitive details are required (eg a bankcard), then the payment details
    view should submit to the preview URL and a custom implementation of
    `validate_payment_submission` should be provided.

    - If the form data is valid, then the preview template can be rendered with
      the payment-details forms re-rendered within a hidden div so they can be
      re-submitted when the 'place order' button is clicked. This avoids having
      to write sensitive data to disk anywhere during the process. This can be
      done by calling `render_preview`, passing in the extra template context
      vars.

    - If the form data is invalid, then the payment details templates needs to
      be re-rendered with the relevant error messages. This can be done by
      calling `render_payment_details`, passing in the form instances to pass
      to the templates.

    The class is deliberately split into fine-grained methods, responsible for
    only one thing.  This is to make it easier to subclass and override just
    one component of functionality.

    All projects will need to subclass and customise this class as no payment
    is taken by default.

    用于获取付款和创建订单的详细信息。

    此视图类由两个单独的URL使用：“payment-details”和“preview”。
    `preview`类属性用于区分正在使用的属性。 按时间顺序，
    'payment-details`（preview = False）出现在`preview`（preview = True）之前。

    如果需要敏感细节（例如银行卡），则支付详细信息视图应提交给预览URL，并且应
    提供“validate_payment_submission”的自定义实现。

    - 如果表单数据有效，则可以呈现预览模板，并在隐藏的div中重新呈现付款详细信息
      表单，以便在单击“下订单”按钮时可以重新提交它们。 这样可以避免在此过程中
      将敏感数据写入磁盘的任何位置。 这可以通过调用`render_preview`来完成，传入额
      外的模板上下文变量。

    - 如果表单数据无效，则需要使用相关的错误消息重新呈现付款详细信息模板。 这可
      以通过调用`render_payment_details`来完成，传入表单实例以传递给模板。

    这个课程被故意分成细粒度的方法，只负责一件事。 这是为了更容易子类化和覆盖一个功能组件。

    所有项目都需要子类化并自定义此类，因为默认情况下不进行任何付款。
    """
    template_name = 'checkout/payment_details.html'
    template_name_preview = 'checkout/preview.html'

    # These conditions are extended at runtime depending on whether we are in
    # 'preview' mode or not.
    # 这些条件在运行时延长，具体取决于我们是否处于“预览”模式。
    pre_conditions = [
        'check_basket_is_not_empty',
        'check_basket_is_valid',
        'check_user_email_is_captured',
        'check_shipping_data_is_captured']

    # If preview=True, then we render a preview template that shows all order
    # details ready for submission.
    # 如果preview = True，那么我们会渲染一个预览模板，显示准备提交的所有订单详细信息。
    preview = False

    # 获得先决条件
    def get_pre_conditions(self, request):
        if self.preview:
            # The preview view needs to ensure payment information has been
            # correctly captured.
            # 预览视图需要确保已正确捕获付款信息。
            return self.pre_conditions + ['check_payment_data_is_captured']
        return super().get_pre_conditions(request)

    # 得到跳过条件
    def get_skip_conditions(self, request):
        if not self.preview:
            # Payment details should only be collected if necessary
            # 只有在必要时才能收集付款详情
            return ['skip_unless_payment_is_required']
        return super().get_skip_conditions(request)

    def post(self, request, *args, **kwargs):
        # Posting to payment-details isn't the right thing to do.  Form
        # submissions should use the preview URL.
        # 发布付款详情不是正确的做法。 表单提交应使用预览URL。
        if not self.preview:
            return http.HttpResponseBadRequest()

        # We use a custom parameter to indicate if this is an attempt to place
        # an order (normally from the preview page).  Without this, we assume a
        # payment form is being submitted from the payment details view. In
        # this case, the form needs validating and the order preview shown.
        # 我们使用自定义参数来指示这是否是尝试下订单（通常来自预览页面）。 如果
        # 没有这个，我们假设从付款明细视图中提交了付款表单。 在这种情况下，表单
        # 需要验证并显示订单预览。
        if request.POST.get('action', '') == 'place_order':
            return self.handle_place_order_submission(request)
        return self.handle_payment_details_submission(request)

    # 处理下单提交
    def handle_place_order_submission(self, request):
        """
        Handle a request to place an order.

        This method is normally called after the customer has clicked "place
        order" on the preview page. It's responsible for (re-)validating any
        form information then building the submission dict to pass to the
        `submit` method.

        If forms are submitted on your payment details view, you should
        override this method to ensure they are valid before extracting their
        data into the submission dict and passing it onto `submit`.

        处理下订单的请求。

        通常在客户点击预览页面上的“下订单”后调用此方法。 它负责（重新）验证
        任何表单信息，然后构建提交字典以传递给`submit`方法。

        如果在您的付款详细信息视图中提交表单，您应该覆盖此方法以确保它们在将数
        据提取到提交字典并将其传递到“submit”之前有效。
        """
        return self.submit(**self.build_submission())

    # 处理付款细节提交
    def handle_payment_details_submission(self, request):
        """
        Handle a request to submit payment details.

        This method will need to be overridden by projects that require forms
        to be submitted on the payment details view.  The new version of this
        method should validate the submitted form data and:

        - If the form data is valid, show the preview view with the forms
          re-rendered in the page
        - If the form data is invalid, show the payment details view with
          the form errors showing.

        处理提交付款详细信息的请求。

        需要在付款详细信息视图中提交表单的项目将覆盖此方法。
        此方法的新版本应验证提交的表单数据并：

        - 如果表单数据有效，则显示预览视图，并在页面中重新呈现表单
        - 如果表单数据无效，请显示显示表单错误的付款详细信息视图。
        """
        # No form data to validate by default, so we simply render the preview
        # page.  If validating form data and it's invalid, then call the
        # render_payment_details view.
        # 没有默认情况下要验证的表单数据，因此我们只需渲染预览页面。 如果验证
        # 表单数据并且它无效，则调用render_payment_details视图。
        return self.render_preview(request)

    # 渲染预览
    def render_preview(self, request, **kwargs):
        """
        Show a preview of the order.

        If sensitive data was submitted on the payment details page, you will
        need to pass it back to the view here so it can be stored in hidden
        form inputs.  This avoids ever writing the sensitive data to disk.

        显示订单的预览。

        如果在付款详细信息页面上提交了敏感数据，则需要将其传递回此处的视图，以
        便将其存储在隐藏表单输入中。 这可以避免将敏感数据写入磁盘。
        """
        self.preview = True
        ctx = self.get_context_data(**kwargs)
        return self.render_to_response(ctx)

    # 呈现付款细节
    def render_payment_details(self, request, **kwargs):
        """
        Show the payment details page

        This method is useful if the submission from the payment details view
        is invalid and needs to be re-rendered with form errors showing.

        显示付款明细页面

        如果来自付款详细信息视图的提交无效并且需要在显示表单错误时重新呈现，则
        此方法很有用。
        """
        self.preview = False
        ctx = self.get_context_data(**kwargs)
        return self.render_to_response(ctx)

    # 获取默认帐单邮寄地址
    def get_default_billing_address(self):
        """
        Return default billing address for user

        This is useful when the payment details view includes a billing address
        form - you can use this helper method to prepopulate the form.

        Note, this isn't used in core oscar as there is no billing address form
        by default.

        返回用户的默认帐单邮寄地址

        当付款详细信息视图包含帐单邮寄地址表单时，此功能非常有用 - 您可以使用此
        帮助程序方法预填充表单。

        注意，这不用于核心oscar，因为默认情况下没有帐单地址表。
        """
        if not self.request.user.is_authenticated:
            return None
        try:
            return self.request.user.addresses.get(is_default_for_billing=True)
        except UserAddress.DoesNotExist:
            return None

    # 提交
    def submit(self, user, basket, shipping_address, shipping_method,  # noqa (too complex (10))
               shipping_charge, billing_address, order_total,
               payment_kwargs=None, order_kwargs=None):
        """
        Submit a basket for order placement.

        The process runs as follows:

         * Generate an order number
         * Freeze the basket so it cannot be modified any more (important when
           redirecting the user to another site for payment as it prevents the
           basket being manipulated during the payment process).
         * Attempt to take payment for the order
           - If payment is successful, place the order
           - If a redirect is required (eg PayPal, 3DSecure), redirect
           - If payment is unsuccessful, show an appropriate error message

        :basket: The basket to submit.
        :payment_kwargs: Additional kwargs to pass to the handle_payment
                         method. It normally makes sense to pass form
                         instances (rather than model instances) so that the
                         forms can be re-rendered correctly if payment fails.
        :order_kwargs: Additional kwargs to pass to the place_order method

        提交购物篮以进行下单。

        该过程如下：
        * 生成订单号
        * 冻结购物篮使其不能再被修改（在将用户重定向到另一个站点进行支付时很
          重要，因为它可以防止在支付过程中操纵购物篮）。
        * 尝试为订单付款
           - 如果付款成功，请下订单
           - 如果需要重定向（例如PayPal，3DSecure），则重定向
           - 如果付款失败，请显示相应的错误消息
        """
        if payment_kwargs is None:
            payment_kwargs = {}
        if order_kwargs is None:
            order_kwargs = {}

        # Taxes must be known at this point
        # 此时必须知道税收
        assert basket.is_tax_known, (
            "Basket tax must be set before a user can place an order")
        # 必须在用户下订单之前设置购物篮税
        assert shipping_charge.is_tax_known, (
            "Shipping charge tax must be set before a user can place an order")
        # 必须在用户下订单之前设置运费

        # We generate the order number first as this will be used
        # in payment requests (ie before the order model has been
        # created).  We also save it in the session for multi-stage
        # checkouts (eg where we redirect to a 3rd party site and place
        # the order on a different request).
        # 我们首先生成订单号，因为它将用于付款请求（即在创建订单模型之前）。
        # 我们还将其保存在多阶段结账的会话中（例如，我们重定向到第三方网站并
        # 将订单放在不同的请求上）。
        order_number = self.generate_order_number(basket)
        self.checkout_session.set_order_number(order_number)
        logger.info("Order #%s: beginning submission process for basket #%d",
                    order_number, basket.id)

        # Freeze the basket so it cannot be manipulated while the customer is
        # completing payment on a 3rd party site.  Also, store a reference to
        # the basket in the session so that we know which basket to thaw if we
        # get an unsuccessful payment response when redirecting to a 3rd party
        # site.
        # 冻结购物篮，以便在客户在第三方网站上完成付款时无法操纵它。 此外，在会
        # 话中存储对购物篮的引用，以便在重定向到第三方站点时，如果我们收到不成
        # 功的付款响应，我们就知道要解冻哪个购物篮。
        self.freeze_basket(basket)
        self.checkout_session.set_submitted_basket(basket)

        # We define a general error message for when an unanticipated payment
        # error occurs.
        # 我们为发生意外付款错误的时间定义一般错误消息。
        error_msg = _("A problem occurred while processing payment for this "
                      "order - no payment has been taken.  Please "
                      "contact customer services if this problem persists")
        # 处理此订单的付款时出现问题 - 未付款。 如果此问题仍然存在，请联系客户服务

        signals.pre_payment.send_robust(sender=self, view=self)

        try:
            self.handle_payment(order_number, order_total, **payment_kwargs)
        except RedirectRequired as e:
            # Redirect required (eg PayPal, 3DS)
            # 需要重定向（例如PayPal，3DS）
            logger.info("Order #%s: redirecting to %s", order_number, e.url)
            return http.HttpResponseRedirect(e.url)
        except UnableToTakePayment as e:
            # Something went wrong with payment but in an anticipated way.  Eg
            # their bankcard has expired, wrong card number - that kind of
            # thing. This type of exception is supposed to set a friendly error
            # message that makes sense to the customer.
            # 支付出现问题但是以预期的方式出现了问题。 例如，他们的银行卡已过
            # 期，卡号错误 - 这种事情。 这种类型的异常应该设置一个对客户有意
            # 义的友好错误消息。
            msg = str(e)
            logger.warning(
                "Order #%s: unable to take payment (%s) - restoring basket",
                order_number, msg)
            self.restore_frozen_basket()

            # We assume that the details submitted on the payment details view
            # were invalid (eg expired bankcard).
            # 我们假设在付款明细视图上提交的详细信息无效（例如过期的银行卡）。
            return self.render_payment_details(
                self.request, error=msg, **payment_kwargs)
        except PaymentError as e:
            # A general payment error - Something went wrong which wasn't
            # anticipated.  Eg, the payment gateway is down (it happens), your
            # credentials are wrong - that king of thing.
            # It makes sense to configure the checkout logger to
            # mail admins on an error as this issue warrants some further
            # investigation.
            # 一般的付款错误 - 出现了错误，这是没有预料到的。 例如，
            # 支付网关已关闭（它发生了），您的凭据是错误的
            msg = str(e)
            logger.error("Order #%s: payment error (%s)", order_number, msg,
                         exc_info=True)
            self.restore_frozen_basket()
            return self.render_preview(
                self.request, error=error_msg, **payment_kwargs)
        except Exception as e:
            # Unhandled exception - hopefully, you will only ever see this in
            # development...
            # 未处理的异常 - 希望你只会在开发中看到这个...
            logger.error(
                "Order #%s: unhandled exception while taking payment (%s)",
                order_number, e, exc_info=True)
            self.restore_frozen_basket()
            return self.render_preview(
                self.request, error=error_msg, **payment_kwargs)

        signals.post_payment.send_robust(sender=self, view=self)

        # If all is ok with payment, try and place order
        # 如果付款都可以，请尝试下订单
        logger.info("Order #%s: payment successful, placing order",
                    order_number)
        try:
            return self.handle_order_placement(
                order_number, user, basket, shipping_address, shipping_method,
                shipping_charge, billing_address, order_total, **order_kwargs)
        except UnableToPlaceOrder as e:
            # It's possible that something will go wrong while trying to
            # actually place an order.  Not a good situation to be in as a
            # payment transaction may already have taken place, but needs
            # to be handled gracefully.
            # 在尝试实际下订单时，可能会出现问题。 由于支付交易可能已经发生，
            # 但并不是一个好的情况，但需要优雅地处理。
            msg = str(e)
            logger.error("Order #%s: unable to place order - %s",
                         order_number, msg, exc_info=True)
            self.restore_frozen_basket()
            return self.render_preview(
                self.request, error=msg, **payment_kwargs)

    def get_template_names(self):
        return [self.template_name_preview] if self.preview else [
            self.template_name]


# =========
# Thank you
# =========


class ThankYouView(generic.DetailView):
    """
    Displays the 'thank you' page which summarises the order just submitted.
    显示“谢谢”页面，其中汇总了刚刚提交的订单。
    """
    template_name = 'checkout/thank_you.html'
    context_object_name = 'order'

    def get_object(self):
        # We allow superusers to force an order thank-you page for testing
        # 我们允许超级用户强制进行测试的感谢页面
        order = None
        if self.request.user.is_superuser:
            if 'order_number' in self.request.GET:
                order = Order._default_manager.get(
                    number=self.request.GET['order_number'])
            elif 'order_id' in self.request.GET:
                order = Order._default_manager.get(
                    id=self.request.GET['order_id'])

        if not order:
            if 'checkout_order_id' in self.request.session:
                order = Order._default_manager.get(
                    pk=self.request.session['checkout_order_id'])
            else:
                raise http.Http404(_("No order found"))

        return order

    def get_context_data(self, *args, **kwargs):
        ctx = super().get_context_data(*args, **kwargs)
        # Remember whether this view has been loaded.
        # Only send tracking information on the first load.
        # 请记住是否已加载此视图。 仅在第一次加载时发送跟踪信息。
        key = 'order_{}_thankyou_viewed'.format(ctx['order'].pk)
        if not self.request.session.get(key, False):
            self.request.session[key] = True
            ctx['send_analytics_event'] = True
        else:
            ctx['send_analytics_event'] = False

        return ctx
