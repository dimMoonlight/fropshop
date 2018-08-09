from decimal import Decimal as D

from django import http
from django.contrib import messages
from django.core.exceptions import ImproperlyConfigured
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from oscar.core import prices
from oscar.core.loading import get_class, get_model

from . import exceptions

Repository = get_class('shipping.repository', 'Repository')
OrderTotalCalculator = get_class(
    'checkout.calculators', 'OrderTotalCalculator')
CheckoutSessionData = get_class(
    'checkout.utils', 'CheckoutSessionData')
ShippingAddress = get_model('order', 'ShippingAddress')
BillingAddress = get_model('order', 'BillingAddress')
UserAddress = get_model('address', 'UserAddress')


# 结账会话Mixin
class CheckoutSessionMixin(object):
    """
    Mixin to provide common functionality shared between checkout views.

    All checkout views subclass this mixin. It ensures that all relevant
    checkout information is available in the template context.

    Mixin提供结帐视图之间共享的常用功能。

    所有结帐视图都是这个mixin的子类。 它确保在模板上下文中提供所有相关的结帐信息。
    """

    # A pre-condition is a condition that MUST be met in order for a view
    # to be available. If it isn't then the customer should be redirected
    # to a view *earlier* in the chain.
    # pre_conditions is a list of method names that get executed before the
    # normal flow of the view. Each method should check some condition has been
    # met. If not, then an exception is raised that indicates the URL the
    # customer will be redirected to.
    # 前提条件是必须满足的条件才能使视图可用。 如果不是，则应将客户重定向到链中的视图*之前*。
    # pre_conditions是在视图正常流之前执行的方法名称列表。 每种方法都应该检查
    # 一些已满足的条件。 如果没有，则会引发异常，指示客户将被重定向到的URL。
    pre_conditions = None

    # A *skip* condition is a condition that MUST NOT be met in order for a
    # view to be available. If the condition is met, this means the view MUST
    # be skipped and the customer should be redirected to a view *later* in
    # the chain.
    # Skip conditions work similar to pre-conditions, and get evaluated after
    # pre-conditions have been evaluated.

    # A * skip *条件是为了使视图可用而不能满足的条件。 如果条件满足，
    # 这意味着必须跳过视图，并且应该将客户重定向到链中的* *之后的视图。
    # 跳过条件与前置条件类似，并在评估前置条件后进行评估。

    skip_conditions = None

    # 调度
    def dispatch(self, request, *args, **kwargs):
        # Assign the checkout session manager so it's available in all checkout
        # views.
        # 分配结帐会话管理器，使其在所有结帐视图中可用。
        self.checkout_session = CheckoutSessionData(request)

        # Enforce any pre-conditions for the view.
        # 强制执行视图的任何前提条件。
        try:
            self.check_pre_conditions(request)
        except exceptions.FailedPreCondition as e:
            for message in e.messages:
                messages.warning(request, message)
            return http.HttpResponseRedirect(e.url)

        # Check if this view should be skipped
        # 检查是否应跳过此视图
        try:
            self.check_skip_conditions(request)
        except exceptions.PassedSkipCondition as e:
            return http.HttpResponseRedirect(e.url)

        return super().dispatch(
            request, *args, **kwargs)

    # 检查前置条件
    def check_pre_conditions(self, request):
        pre_conditions = self.get_pre_conditions(request)
        for method_name in pre_conditions:
            if not hasattr(self, method_name):
                raise ImproperlyConfigured(
                    "There is no method '%s' to call as a pre-condition" % (
                        method_name))
            # 没有方法'％s'作为前置条件调用
            getattr(self, method_name)(request)

    # 获得先决条件
    def get_pre_conditions(self, request):
        """
        Return the pre-condition method names to run for this view
        返回为此视图运行的前置条件方法名称
        """
        if self.pre_conditions is None:
            return []
        return self.pre_conditions

    # 检查跳过条件
    def check_skip_conditions(self, request):
        skip_conditions = self.get_skip_conditions(request)
        for method_name in skip_conditions:
            if not hasattr(self, method_name):
                raise ImproperlyConfigured(
                    "There is no method '%s' to call as a skip-condition" % (
                        method_name))
            # 没有方法'％s'可以作为跳过条件调用
            getattr(self, method_name)(request)

    # 得到跳过条件
    def get_skip_conditions(self, request):
        """
        Return the skip-condition method names to run for this view
        返回要为此视图运行的skip-condition方法名称
        """
        if self.skip_conditions is None:
            return []
        return self.skip_conditions

    # Re-usable pre-condition validators
    # 可重复使用的前置条件验证器

    # 检查购物篮不是空的
    def check_basket_is_not_empty(self, request):
        if request.basket.is_empty:
            raise exceptions.FailedPreCondition(
                url=reverse('basket:summary'),
                message=_(
                    "You need to add some items to your basket to checkout")
            )
        # 您需要在购物篮中添加一些商品才能结帐

    # 检查购物篮有效
    def check_basket_is_valid(self, request):
        """
        Check that the basket is permitted to be submitted as an order. That
        is, all the basket lines are available to buy - nothing has gone out of
        stock since it was added to the basket.

        检查允许将购物篮作为订单提交。 也就是说，所有购物篮行都可以买到 - 因为
        它被添加到购物篮里，所以没有任何东西已经缺货。
        """
        messages = []
        strategy = request.strategy
        for line in request.basket.all_lines():
            result = strategy.fetch_for_line(line)
            is_permitted, reason = result.availability.is_purchase_permitted(
                line.quantity)
            if not is_permitted:
                # Create a more meaningful message to show on the basket page
                # 创建更有意义的消息以显示在购物篮页面上
                msg = _(
                    "'%(title)s' is no longer available to buy (%(reason)s). "
                    "Please adjust your basket to continue"
                ) % {
                    'title': line.product.get_title(),
                    'reason': reason}
                # '％（标题）s'不再可供购买（％（原因）s）。 请调整你的购物篮继续
                messages.append(msg)
        if messages:
            raise exceptions.FailedPreCondition(
                url=reverse('basket:summary'),
                messages=messages
            )

    # 检查用户电子邮件
    def check_user_email_is_captured(self, request):
        if not request.user.is_authenticated \
                and not self.checkout_session.get_guest_email():
            raise exceptions.FailedPreCondition(
                url=reverse('checkout:index'),
                message=_(
                    "Please either sign in or enter your email address")
            )
        # 请登录或输入您的电子邮件地址

    # 检查运输数据
    def check_shipping_data_is_captured(self, request):
        if not request.basket.is_shipping_required():
            # Even without shipping being required, we still need to check that
            # a shipping method code has been set.
            # 即使不需要运输，我们仍需要检查是否已设置运输方法代码。
            if not self.checkout_session.is_shipping_method_set(
                    self.request.basket):
                raise exceptions.FailedPreCondition(
                    url=reverse('checkout:shipping-method'),
                )
            return

        # Basket requires shipping: check address and method are captured and
        # valid.
        # 购物篮需要发货：检查地址和方法是有效的。
        self.check_a_valid_shipping_address_is_captured()
        self.check_a_valid_shipping_method_is_captured()

    # 检查有效的送货地址
    def check_a_valid_shipping_address_is_captured(self):
        # Check that shipping address has been completed
        # 检查送货地址是否已完成
        if not self.checkout_session.is_shipping_address_set():
            raise exceptions.FailedPreCondition(
                url=reverse('checkout:shipping-address'),
                message=_("Please choose a shipping address")
            )
        # 请选择送货地址

        # Check that the previously chosen shipping address is still valid
        # 检查先前选择的送货地址是否仍然有效
        shipping_address = self.get_shipping_address(
            basket=self.request.basket)
        if not shipping_address:
            raise exceptions.FailedPreCondition(
                url=reverse('checkout:shipping-address'),
                message=_("Your previously chosen shipping address is "
                          "no longer valid.  Please choose another one")
            )
        # 您之前选择的送货地址不再有效。 请选择另一个

    # 检查是否已捕获有效的送货方式
    def check_a_valid_shipping_method_is_captured(self):
        # Check that shipping method has been set
        # 检查是否已设置送货方式
        if not self.checkout_session.is_shipping_method_set(
                self.request.basket):
            raise exceptions.FailedPreCondition(
                url=reverse('checkout:shipping-method'),
                message=_("Please choose a shipping method")
            )

        # Check that a *valid* shipping method has been set
        # 检查是否已设置*有效*送货方式
        shipping_address = self.get_shipping_address(
            basket=self.request.basket)
        shipping_method = self.get_shipping_method(
            basket=self.request.basket,
            shipping_address=shipping_address)
        if not shipping_method:
            raise exceptions.FailedPreCondition(
                url=reverse('checkout:shipping-method'),
                message=_("Your previously chosen shipping method is "
                          "no longer valid.  Please choose another one")
            )
        # 您之前选择的送货方式不再有效。 请选择另一个

    # 检查支付数据
    def check_payment_data_is_captured(self, request):
        # We don't collect payment data by default so we don't have anything to
        # validate here. If your shop requires forms to be submitted on the
        # payment details page, then override this method to check that the
        # relevant data is available. Often just enforcing that the preview
        # view is only accessible from a POST request is sufficient.
        # 我们默认不收集付款数据，因此我们没有任何要验证的内容。 如果您的商店
        # 要求在付款明细页面上提交表单，请覆盖此方法以检查相关数据是否可用。
        # 通常只强制执行只能从POST请求访问预览视图就足够了。
        pass

    # Re-usable skip conditions
    # 可重复使用的跳过条件

    # 跳过，除非购物篮需要运输
    def skip_unless_basket_requires_shipping(self, request):
        # Check to see that a shipping address is actually required.  It may
        # not be if the basket is purely downloads
        # 检查是否确实需要送货地址。 如果购物篮是纯粹的下载，可能不是这样
        if not request.basket.is_shipping_required():
            raise exceptions.PassedSkipCondition(
                url=reverse('checkout:shipping-method')
            )

    # 除非需要付款，否则跳过
    def skip_unless_payment_is_required(self, request):
        # Check to see if payment is actually required for this order.
        # 检查此订单是否确实需要付款。
        shipping_address = self.get_shipping_address(request.basket)
        shipping_method = self.get_shipping_method(
            request.basket, shipping_address)
        if shipping_method:
            shipping_charge = shipping_method.calculate(request.basket)
        else:
            # It's unusual to get here as a shipping method should be set by
            # the time this skip-condition is called. In the absence of any
            # other evidence, we assume the shipping charge is zero.
            # 到达这里是不寻常的，因为运输方法应该在调用此跳过条件时设置。
            # 在没有任何其他证据的情况下，我们假设运费为零。
            shipping_charge = prices.Price(
                currency=request.basket.currency, excl_tax=D('0.00'),
                tax=D('0.00')
            )
        total = self.get_order_totals(request.basket, shipping_charge)
        if total.excl_tax == D('0.00'):
            raise exceptions.PassedSkipCondition(
                url=reverse('checkout:preview')
            )

    # Helpers 助手

    # 获取上下文数据
    def get_context_data(self, **kwargs):
        # Use the proposed submission as template context data.  Flatten the
        # order kwargs so they are easily available too.
        # 使用建议的提交作为模板上下文数据。 压缩订单kwargs，以便它们也很容易获得。
        ctx = super().get_context_data()
        ctx.update(self.build_submission(**kwargs))
        ctx.update(kwargs)
        ctx.update(ctx['order_kwargs'])
        return ctx

    # 构建提交
    def build_submission(self, **kwargs):
        """
        Return a dict of data that contains everything required for an order
        submission.  This includes payment details (if any).

        This can be the right place to perform tax lookups and apply them to
        the basket.

        返回包含订单提交所需内容的数据字典。 这包括付款详细信息（如果有）。
        这可以是执行税务查询并将其应用于购物篮的正确位置。
        """
        # Pop the basket if there is one, because we pass it as a positional
        # argument to methods below
        # 如果有购物篮，则弹出购物篮，因为我们将它作为位置参数传递给下面的方法
        basket = kwargs.pop('basket', self.request.basket)
        shipping_address = self.get_shipping_address(basket)
        shipping_method = self.get_shipping_method(
            basket, shipping_address)
        billing_address = self.get_billing_address(shipping_address)
        if not shipping_method:
            total = shipping_charge = None
        else:
            shipping_charge = shipping_method.calculate(basket)
            total = self.get_order_totals(
                basket, shipping_charge=shipping_charge, **kwargs)
        submission = {
            'user': self.request.user,
            'basket': basket,
            'shipping_address': shipping_address,
            'shipping_method': shipping_method,
            'shipping_charge': shipping_charge,
            'billing_address': billing_address,
            'order_total': total,
            'order_kwargs': {},
            'payment_kwargs': {}}

        # If there is a billing address, add it to the payment kwargs as calls
        # to payment gateways generally require the billing address. Note, that
        # it normally makes sense to pass the form instance that captures the
        # billing address information. That way, if payment fails, you can
        # render bound forms in the template to make re-submission easier.
        # 如果有帐单邮寄地址，请将其添加到付款kwargs，因为对付款网关的呼叫通常需
        # 要帐单邮寄地址。 请注意，传递捕获帐单邮寄地址信息的表单实例通常是有
        # 意义的。 这样，如果付款失败，您可以在模板中呈现绑定的表单，以便更轻松
        # 地重新提交。
        if billing_address:
            submission['payment_kwargs']['billing_address'] = billing_address

        # Allow overrides to be passed in
        # 允许覆盖传递
        submission.update(kwargs)

        # Set guest email after overrides as we need to update the order_kwargs
        # entry.
        # 在覆盖后设置访客电子邮件，因为我们需要更新order_kwargs条目。
        user = submission['user']
        if (not user.is_authenticated and
                'guest_email' not in submission['order_kwargs']):
            email = self.checkout_session.get_guest_email()
            submission['order_kwargs']['guest_email'] = email
        return submission

    # 获取送货地址
    def get_shipping_address(self, basket):
        """
        Return the (unsaved) shipping address for this checkout session.

        If the shipping address was entered manually, then we instantiate a
        ``ShippingAddress`` model with the appropriate form data (which is
        saved in the session).

        If the shipping address was selected from the user's address book,
        then we convert the ``UserAddress`` to a ``ShippingAddress``.

        The ``ShippingAddress`` instance is not saved as sometimes you need a
        shipping address instance before the order is placed.  For example, if
        you are submitting fraud information as part of a payment request.

        The ``OrderPlacementMixin.create_shipping_address`` method is
        responsible for saving a shipping address when an order is placed.

        返回此结帐会话的（未保存的）送货地址。

        如果手动输入发货地址，那么我们使用适当的表单数据（保存在会话中）实例化一个“ShippingAddress”模型。
        如果从用户的地址簿中选择了送货地址，那么我们将``UserAddress``转换为``ShippingAddress``。

        “ShippingAddress``实例未保存，因为有时您需要在下订单之前提供送货地址实例。
         例如，如果您要将欺诈信息作为付款请求的一部分提交。

        “OrderPlacementMixin.create_shipping_address``方法负责在下订单时保存送货地址。
        """
        if not basket.is_shipping_required():
            return None

        addr_data = self.checkout_session.new_shipping_address_fields()
        if addr_data:
            # Load address data into a blank shipping address model
            # 将地址数据加载到空白送货地址模型中
            return ShippingAddress(**addr_data)
        addr_id = self.checkout_session.shipping_user_address_id()
        if addr_id:
            try:
                address = UserAddress._default_manager.get(pk=addr_id)
            except UserAddress.DoesNotExist:
                # An address was selected but now it has disappeared.  This can
                # happen if the customer flushes their address book midway
                # through checkout.  No idea why they would do this but it can
                # happen.  Checkouts are highly vulnerable to race conditions
                # like this.
                # 选择了一个地址，但现在它已经消失了。 如果客户在结账中途刷新他
                # 们的地址簿，就会发生这种情况。 不知道为什么他们会这样做，但它
                # 可能会发生。 结帐非常容易受到这样的竞争条件的影响。
                return None
            else:
                # Copy user address data into a blank shipping address instance
                # 将用户地址数据复制到空白送货地址实例中
                shipping_addr = ShippingAddress()
                address.populate_alternative_model(shipping_addr)
                return shipping_addr

    # 获得运输方式
    def get_shipping_method(self, basket, shipping_address=None, **kwargs):
        """
        Return the selected shipping method instance from this checkout session

        The shipping address is passed as we need to check that the method
        stored in the session is still valid for the shipping address.

        从此结帐会话中返回选定的送货方法实例
        由于我们需要检查存储在会话中的方法是否仍对送货地址有效，因此传递送货地址。
        """
        code = self.checkout_session.shipping_method_code(basket)
        methods = Repository().get_shipping_methods(
            basket=basket, user=self.request.user,
            shipping_addr=shipping_address, request=self.request)
        for method in methods:
            if method.code == code:
                return method

    # 获取帐单地址
    def get_billing_address(self, shipping_address):
        """
        Return an unsaved instance of the billing address (if one exists)

        This method only returns a billing address if the session has been used
        to store billing address information. It's also possible to capture
        billing address information as part of the payment details forms, which
        never get stored in the session. In that circumstance, the billing
        address can be set directly in the build_submission dict.

        返回未保存的帐单邮寄地址实例（如果存在）

        如果会话已用于存储帐单地址信息，则此方法仅返回帐单地址。 还可以将结算
        地址信息作为付款详细信息表单的一部分进行捕获，该表单永远不会存储在会话中。
        在这种情况下，可以直接在build_submission dict中设置帐单地址。
        """
        if not self.checkout_session.is_billing_address_set():
            return None
        if self.checkout_session.is_billing_address_same_as_shipping():
            if shipping_address:
                address = BillingAddress()
                shipping_address.populate_alternative_model(address)
                return address

        addr_data = self.checkout_session.new_billing_address_fields()
        if addr_data:
            # A new billing address has been entered - load address data into a
            # blank billing address model.
            # 已输入新的帐单邮寄地址 - 将地址数据加载到空白帐单邮寄地址模型中。
            return BillingAddress(**addr_data)

        addr_id = self.checkout_session.billing_user_address_id()
        if addr_id:
            # An address from the user's address book has been selected as the
            # billing address - load it and convert it into a billing address
            # instance.
            # 已选择用户地址簿中的地址作为帐单地址 - 加载并将其转换为帐单地址实例。
            try:
                user_address = UserAddress._default_manager.get(pk=addr_id)
            except UserAddress.DoesNotExist:
                # An address was selected but now it has disappeared.  This can
                # happen if the customer flushes their address book midway
                # through checkout.  No idea why they would do this but it can
                # happen.  Checkouts are highly vulnerable to race conditions
                # like this.
                # 选择了一个地址，但现在它已经消失了。 如果客户在结账中途刷新他们
                # 的地址簿，就会发生这种情况。 不知道为什么他们会这样做，但它可能
                # 会发生。 结帐非常容易受到这样的竞争条件的影响。
                return None
            else:
                # Copy user address data into a blank shipping address instance
                # 将用户地址数据复制到空白送货地址实例中
                billing_address = BillingAddress()
                user_address.populate_alternative_model(billing_address)
                return billing_address

    def get_order_totals(self, basket, shipping_charge, **kwargs):
        """
        Returns the total for the order with and without tax
        返回含税和不含税的订单总额
        """
        return OrderTotalCalculator(self.request).calculate(
            basket, shipping_charge, **kwargs)
