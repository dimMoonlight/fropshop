import logging

from django.contrib.sites.models import Site
from django.contrib.sites.shortcuts import get_current_site
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpResponseRedirect
from django.urls import NoReverseMatch, reverse

from oscar.apps.checkout.signals import post_checkout
from oscar.core.loading import get_class, get_model

OrderCreator = get_class('order.utils', 'OrderCreator')
Dispatcher = get_class('customer.utils', 'Dispatcher')
CheckoutSessionMixin = get_class('checkout.session', 'CheckoutSessionMixin')
BillingAddress = get_model('order', 'BillingAddress')
ShippingAddress = get_model('order', 'ShippingAddress')
OrderNumberGenerator = get_class('order.utils', 'OrderNumberGenerator')
PaymentEventType = get_model('order', 'PaymentEventType')
PaymentEvent = get_model('order', 'PaymentEvent')
PaymentEventQuantity = get_model('order', 'PaymentEventQuantity')
UserAddress = get_model('address', 'UserAddress')
Basket = get_model('basket', 'Basket')
CommunicationEventType = get_model('customer', 'CommunicationEventType')
UnableToPlaceOrder = get_class('order.exceptions', 'UnableToPlaceOrder')

# Standard logger for checkout events
# 结帐活动的标准记录器
logger = logging.getLogger('oscar.checkout')


# 订单安置Mxin
class OrderPlacementMixin(CheckoutSessionMixin):
    """
    Mixin which provides functionality for placing orders.

    Any view class which needs to place an order should use this mixin.

    Mixin提供下订单功能。
    任何需要下订单的视图类都应该使用这个mixin。
    """
    # Any payment sources should be added to this list as part of the
    # handle_payment method.  If the order is placed successfully, then
    # they will be persisted. We need to have the order instance before the
    # payment sources can be saved.
    # 任何支付来源都应作为handle_payment方法的一部分添加到此列表中。 如果订单
    # 成功放置，那么它们将被保留。 我们需要在保存付款来源之前拥有订单实例。
    _payment_sources = None

    # Any payment events should be added to this list as part of the
    # handle_payment method.
    # 任何付款事件都应作为handle_payment方法的一部分添加到此列表中。
    _payment_events = None

    # Default code for the email to send after successful checkout
    # 成功结帐后要发送的电子邮件的默认代码
    communication_type_code = 'ORDER_PLACED'

    view_signal = post_checkout

    # Payment handling methods
    # 付款处理方法
    # ------------------------

    # 处理付款
    def handle_payment(self, order_number, total, **kwargs):
        """
        Handle any payment processing and record payment sources and events.

        This method is designed to be overridden within your project.  The
        default is to do nothing as payment is domain-specific.

        This method is responsible for handling payment and recording the
        payment sources (using the add_payment_source method) and payment
        events (using add_payment_event) so they can be
        linked to the order when it is saved later on.

        处理任何付款处理并记录付款来源和事件。

        此方法旨在在项目中重写。 默认情况下不执行任何操作，因为付款是特定于域的。

        此方法负责处理付款和记录付款来源（使用add_payment_source方法）和付款
        事件（使用add_payment_event），以便稍后保存时可以将订单链接到订单。
        """
        pass

    # 添加付款来源
    def add_payment_source(self, source):
        """
        Record a payment source for this order
        记录此订单的付款来源
        """
        if self._payment_sources is None:
            self._payment_sources = []
        self._payment_sources.append(source)

    # 添加付款活动
    def add_payment_event(self, event_type_name, amount, reference=''):
        """
        Record a payment event for creation once the order is placed
        下订单后，记录创建的付款事件
        """
        event_type, __ = PaymentEventType.objects.get_or_create(
            name=event_type_name)
        # We keep a local cache of (unsaved) payment events
        # 我们保留（未保存的）付款事件的本地缓存
        if self._payment_events is None:
            self._payment_events = []
        event = PaymentEvent(
            event_type=event_type, amount=amount,
            reference=reference)
        self._payment_events.append(event)

    # Placing order methods
    # 下订单方法
    # ---------------------

    # 生成订单号
    def generate_order_number(self, basket):
        """
        Return a new order number
        返回新的订单号
        """
        return OrderNumberGenerator().order_number(basket)

    # 处理订单安排
    def handle_order_placement(self, order_number, user, basket,
                               shipping_address, shipping_method,
                               shipping_charge, billing_address, order_total,
                               **kwargs):
        """
        Write out the order models and return the appropriate HTTP response

        We deliberately pass the basket in here as the one tied to the request
        isn't necessarily the correct one to use in placing the order.  This
        can happen when a basket gets frozen.

        写出订单模型并返回适当的HTTP响应

        我们故意在这里通过购物篮，因为与请求相关的那个不一定是用于下订单的正确的。
        当购物篮冻结时会发生这种情况。
        """
        order = self.place_order(
            order_number=order_number, user=user, basket=basket,
            shipping_address=shipping_address, shipping_method=shipping_method,
            shipping_charge=shipping_charge, order_total=order_total,
            billing_address=billing_address, **kwargs)
        basket.submit()
        return self.handle_successful_order(order)

    # 下订单
    def place_order(self, order_number, user, basket, shipping_address,
                    shipping_method, shipping_charge, order_total,
                    billing_address=None, **kwargs):
        """
        Writes the order out to the DB including the payment models
        将订单写入数据库，包括支付模型
        """
        # Create saved shipping address instance from passed in unsaved
        # instance
        # 从未保存的实例中传递创建已保存的送货地址实例
        shipping_address = self.create_shipping_address(user, shipping_address)

        # We pass the kwargs as they often include the billing address form
        # which will be needed to save a billing address.
        # 我们通过kwargs，因为它们通常包含保存帐单地址所需的帐单地址表单。
        billing_address = self.create_billing_address(
            user, billing_address, shipping_address, **kwargs)

        if 'status' not in kwargs:
            status = self.get_initial_order_status(basket)
        else:
            status = kwargs.pop('status')

        if 'request' not in kwargs:
            request = getattr(self, 'request', None)
        else:
            request = kwargs.pop('request')

        order = OrderCreator().place_order(
            user=user,
            order_number=order_number,
            basket=basket,
            shipping_address=shipping_address,
            shipping_method=shipping_method,
            shipping_charge=shipping_charge,
            total=order_total,
            billing_address=billing_address,
            status=status,
            request=request,
            **kwargs)
        self.save_payment_details(order)
        return order

    # 创建送货地址
    def create_shipping_address(self, user, shipping_address):
        """
        Create and return the shipping address for the current order.

        Compared to self.get_shipping_address(), ShippingAddress is saved and
        makes sure that appropriate UserAddress exists.

        创建并返回当前订单的送货地址。
        与self.get_shipping_address（）相比，保存了送货地址（ShippingAddress）并确保存在
        适当的用户地址（UserAddress）。
        """
        # For an order that only contains items that don't require shipping we
        # won't have a shipping address, so we have to check for it.
        # 对于仅包含不需要运输的物品的订单，我们将没有送货地址，因此我们必须检查它。
        if not shipping_address:
            return None
        shipping_address.save()
        if user.is_authenticated:
            self.update_address_book(user, shipping_address)
        return shipping_address

    # 更新地址簿
    def update_address_book(self, user, addr):
        """
        Update the user's address book based on the new shipping address
        根据新的送货地址更新用户的地址簿
        """
        try:
            user_addr = user.addresses.get(
                hash=addr.generate_hash())
        except ObjectDoesNotExist:
            # Create a new user address
            # 创建一个新的用户地址
            user_addr = UserAddress(user=user)
            addr.populate_alternative_model(user_addr)
        if isinstance(addr, ShippingAddress):
            user_addr.num_orders_as_shipping_address += 1
        if isinstance(addr, BillingAddress):
            user_addr.num_orders_as_billing_address += 1
        user_addr.save()

    # 创建帐单地址
    def create_billing_address(self, user, billing_address=None,
                               shipping_address=None, **kwargs):
        """
        Saves any relevant billing data (eg a billing address).
        保存任何相关的结算数据（例如结算地址）。
        """
        if not billing_address:
            return None
        billing_address.save()
        if user.is_authenticated:
            self.update_address_book(user, billing_address)
        return billing_address

    # 保存付款详情
    def save_payment_details(self, order):
        """
        Saves all payment-related details. This could include a billing
        address, payment sources and any order payment events.

        保存所有与付款相关的详细信息 这可能包括帐单邮寄地址，付款来源和任何订单付款事件。
        """
        self.save_payment_events(order)
        self.save_payment_sources(order)

    # 保存付款事件
    def save_payment_events(self, order):
        """
        Saves any relevant payment events for this order
        保存此订单的所有相关付款事件
        """
        if not self._payment_events:
            return
        for event in self._payment_events:
            event.order = order
            event.save()
            for line in order.lines.all():
                PaymentEventQuantity.objects.create(
                    event=event, line=line, quantity=line.quantity)

    # 保存付款来源
    def save_payment_sources(self, order):
        """
        Saves any payment sources used in this order.

        When the payment sources are created, the order model does not exist
        and so they need to have it set before saving.

        保存此订单中使用的所有付款来源。

        创建付款来源后，订单模型不存在，因此需要在保存之前设置订单模型。
        """
        if not self._payment_sources:
            return
        for source in self._payment_sources:
            source.order = order
            source.save()

    # 获得初始订单状态
    def get_initial_order_status(self, basket):
        return None

    # Post-order methods
    # 下订单方法
    # ------------------

    # 处理成功的订单
    def handle_successful_order(self, order):
        """
        Handle the various steps required after an order has been successfully
        placed.

        Override this view if you want to perform custom actions when an
        order is submitted.

        处理订单成功后所需的各个步骤。

        如果要在提交订单时执行自定义操作，请覆盖此视图。
        """
        # Send confirmation message (normally an email)
        # 发送确认信息（通常是电子邮件）
        self.send_confirmation_message(order, self.communication_type_code)

        # Flush all session data
        # 刷新所有会话数据
        self.checkout_session.flush()

        # Save order id in session so thank-you page can load it
        # 在会话中保存订单ID，所以感谢页面可以加载它
        self.request.session['checkout_order_id'] = order.id

        response = HttpResponseRedirect(self.get_success_url())
        self.send_signal(self.request, response, order)
        return response

    # 发送信号
    def send_signal(self, request, response, order):
        self.view_signal.send(
            sender=self, order=order, user=request.user,
            request=request, response=response)

    # 获得成功网址
    def get_success_url(self):
        return reverse('checkout:thank-you')

    # 发送确认消息
    def send_confirmation_message(self, order, code, **kwargs):
        try:
            ctx = self.get_message_context(order, code)
        except TypeError:
            # It seems like the get_message_context method was overridden and
            # it does not support the code argument yet
            # 看起来get_message_context方法被覆盖了，它还不支持代码参数
            logger.warning(
                'The signature of the get_message_context method has changed, '
                'please update it in your codebase'
            )
            # get_message_context方法的签名已更改，请在您的代码库中更新它
            ctx = self.get_message_context(order)

        try:
            event_type = CommunicationEventType.objects.get(code=code)
        except CommunicationEventType.DoesNotExist:
            # No event-type in database, attempt to find templates for this
            # type and render them immediately to get the messages.  Since we
            # have not CommunicationEventType to link to, we can't create a
            # CommunicationEvent instance.
            # 数据库中没有事件类型，尝试查找此类型的模板并立即呈现它们以获取消息。
            # 由于我们没有要传递的CommunicationEventType，我们无法
            # 创建CommunicationEvent实例。
            messages = CommunicationEventType.objects.get_and_render(code, ctx)
            event_type = None
        else:
            messages = event_type.get_messages(ctx)

        if messages and messages['body']:
            logger.info("Order #%s - sending %s messages", order.number, code)
            dispatcher = Dispatcher(logger)
            dispatcher.dispatch_order_messages(order, messages,
                                               event_type, **kwargs)
        else:
            logger.warning("Order #%s - no %s communication event type",
                           order.number, code)

    # 获取消息上下文
    def get_message_context(self, order, code=None):
        ctx = {
            'user': self.request.user,
            'order': order,
            'site': get_current_site(self.request),
            'lines': order.lines.all()
        }

        if not self.request.user.is_authenticated:
            # Attempt to add the anon order status URL to the email template
            # ctx.
            # 尝试将匿名订单状态URL添加到电子邮件模板ctx。
            try:
                path = reverse('customer:anon-order',
                               kwargs={'order_number': order.number,
                                       'hash': order.verification_hash()})
            except NoReverseMatch:
                # We don't care that much if we can't resolve the URL
                # 如果我们无法解析URL，我们不会那么在意
                pass
            else:
                site = Site.objects.get_current()
                ctx['status_url'] = 'http://%s%s' % (site.domain, path)
        return ctx

    # Basket helpers
    # 购物篮助手
    # --------------

    # 得到提交的购物篮
    def get_submitted_basket(self):
        basket_id = self.checkout_session.get_submitted_basket_id()
        return Basket._default_manager.get(pk=basket_id)

    # 冻结购物篮
    def freeze_basket(self, basket):
        """
        Freeze the basket so it can no longer be modified
        冻结购物篮使其无法再修改
        """
        # We freeze the basket to prevent it being modified once the payment
        # process has started.  If your payment fails, then the basket will
        # need to be "unfrozen".  We also store the basket ID in the session
        # so the it can be retrieved by multistage checkout processes.
        # 我们冻结购物篮以防止在付款流程开始后对其进行修改。 如果您的付款失败，
        # 那么购物篮将需要“解冻”。 我们还将篮子ID存储在会话中，
        # 以便通过多阶段结账流程检索它。
        basket.freeze()

    # 恢复冷冻购物篮
    def restore_frozen_basket(self):
        """
        Restores a frozen basket as the sole OPEN basket.  Note that this also
        merges in any new products that have been added to a basket that has
        been created while payment.

        将冷冻购物篮恢复为唯一的OPEN购物篮。 请注意，这也会合并到已添加到付款
        时创建的购物篮中的任何新产品中。
        """
        try:
            fzn_basket = self.get_submitted_basket()
        except Basket.DoesNotExist:
            # Strange place.  The previous basket stored in the session does
            # not exist.
            # 奇怪的地方。 存储在会话中的前一个篮子不存在。
            pass
        else:
            fzn_basket.thaw()
            if self.request.basket.id != fzn_basket.id:
                fzn_basket.merge(self.request.basket)
                # Use same strategy as current request basket
                # 使用与当前请求购物篮相同的策略
                fzn_basket.strategy = self.request.basket.strategy
                self.request.basket = fzn_basket
