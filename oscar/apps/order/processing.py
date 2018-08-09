from decimal import Decimal as D

from django.utils.translation import gettext_lazy as _

from oscar.apps.order import exceptions
from oscar.core.loading import get_model

ShippingEventQuantity = get_model('order', 'ShippingEventQuantity')
PaymentEventQuantity = get_model('order', 'PaymentEventQuantity')


class EventHandler(object):
    """
    Handle requested order events.

    This is an important class: it houses the core logic of your shop's order
    processing pipeline.

    处理订单事件的请求。
    这是一个重要的课程：它包含了商店订单处理管道的核心逻辑。
    """

    def __init__(self, user=None):
        self.user = user

    # Core API 核心API
    # --------

    def handle_shipping_event(self, order, event_type, lines,
                              line_quantities, **kwargs):
        """
        Handle a shipping event for a given order.

        This is most common entry point to this class - most of your order
        processing should be modelled around shipping events.  Shipping events
        can be used to trigger payment and communication events.

        You will generally want to override this method to implement the
        specifics of you order processing pipeline.

        处理给定订单的运送事件。

        这是此课程最常见的切入点 - 您的大多数订单处理应围绕运输事件进行建模。
        送货事件可用于触发付款和通信事件。

        您通常希望覆盖此方法以实现订单处理管道的细节。
        """
        # Example implementation 示例实现
        self.validate_shipping_event(
            order, event_type, lines, line_quantities, **kwargs)
        return self.create_shipping_event(
            order, event_type, lines, line_quantities, **kwargs)

    def handle_payment_event(self, order, event_type, amount, lines=None,
                             line_quantities=None, **kwargs):
        """
        Handle a payment event for a given order.

        These should normally be called as part of handling a shipping event.
        It is rare to call to this method directly.  It does make sense for
        refunds though where the payment event may be unrelated to a particular
        shipping event and doesn't directly correspond to a set of lines.

        处理给定订单的付款事件。
        通常应将这些作为处理运输事件的一部分来调用。 很少直接调用此方法。 虽然支付
        事件可能与特定的运输事件无关并且不直接对应于一组线路，但退款确实有意义。
        """
        self.validate_payment_event(
            order, event_type, amount, lines, line_quantities, **kwargs)
        return self.create_payment_event(
            order, event_type, amount, lines, line_quantities, **kwargs)

    def handle_order_status_change(self, order, new_status, note_msg=None):
        """
        Handle a requested order status change

        This method is not normally called directly by client code.  The main
        use-case is when an order is cancelled, which in some ways could be
        viewed as a shipping event affecting all lines.

        处理订单状态更改的请求

        客户端代码通常不直接调用此方法。 主要用例是取消订单时，在某些方面可以将
        其视为影响所有订单的发货事件。
        """
        order.set_status(new_status)
        if note_msg:
            self.create_note(order, note_msg)

    # Validation methods 验证方法
    # ------------------

    def validate_shipping_event(self, order, event_type, lines,
                                line_quantities, **kwargs):
        """
        Test if the requested shipping event is permitted.

        If not, raise InvalidShippingEvent

        测试被允许的运送事件的请求
        如果没有，请引发InvalidShippingEvent（无效的运输事件)
        """
        errors = []
        for line, qty in zip(lines, line_quantities):
            # The core logic should be in the model.  Ensure you override
            # 'is_shipping_event_permitted' and enforce the correct order of
            # shipping events.
            # 核心逻辑应该在模型中。 确保覆盖'is_shipping_event_permitted'并强制
            # 执行正确的送货事件顺序。
            if not line.is_shipping_event_permitted(event_type, qty):
                msg = _("The selected quantity for line #%(line_id)s is too"
                        " large") % {'line_id': line.id}
                errors.append(msg)
        if errors:
            raise exceptions.InvalidShippingEvent(", ".join(errors))

    def validate_payment_event(self, order, event_type, amount, lines=None,
                               line_quantities=None, **kwargs):
        if lines and line_quantities:
            errors = []
            for line, qty in zip(lines, line_quantities):
                if not line.is_payment_event_permitted(event_type, qty):
                    msg = _("The selected quantity for line #%(line_id)s is too"
                            " large") % {'line_id': line.id}
                    errors.append(msg)
            if errors:
                raise exceptions.InvalidPaymentEvent(", ".join(errors))

    # Query methods 查询方法
    # -------------
    # These are to help determine the status of lines
    # 这些是为了帮助确定行的状态

    def have_lines_passed_shipping_event(self, order, lines, line_quantities,
                                         event_type):
        """
        Test whether the passed lines and quantities have been through the
        specified shipping event.

        This is useful for validating if certain shipping events are allowed
        (ie you can't return something before it has shipped).

        测试传递的行和数量是否已通过指定的装运事件。
        这对于验证是否允许某些运输事件非常有用（即您在发货前无法退货）。
        """
        for line, line_qty in zip(lines, line_quantities):
            if line.shipping_event_quantity(event_type) < line_qty:
                return False
        return True

    # Payment stuff 现金支付
    # -------------

    def calculate_payment_event_subtotal(self, event_type, lines,
                                         line_quantities):
        """
        Calculate the total charge for the passed event type, lines and line
        quantities.

        This takes into account the previous prices that have been charged for
        this event.

        Note that shipping is not including in this subtotal.  You need to
        subclass and extend this method if you want to include shipping costs.

        计算传递的事件类型，行数和行数的总费用。
        这考虑了此事件的先前价格。
        请注意，运费不包括在此小计中。 如果要包含运费，则需要对此方法进行子类化和扩展。
        """
        total = D('0.00')
        for line, qty_to_consume in zip(lines, line_quantities):
            # This part is quite fiddly.  We need to skip the prices that have
            # already been settled.  This involves keeping a load of counters.

            # Count how many of this line have already been involved in an
            # event of this type.

            # 这部分非常繁琐。 我们需要跳过已经解决的价格。 这涉及保持计数器的负载。。
            # 计算此类事件中已涉及多少行。
            qty_to_skip = line.payment_event_quantity(event_type)

            # Test if request is sensible
            # 测试请求是否合理
            if qty_to_skip + qty_to_consume > line.quantity:
                raise exceptions.InvalidPaymentEvent

            # Consume prices in order of ID (this is the default but it's
            # better to be explicit)
            # 按ID顺序消费价格（这是默认的，但最好是明确的）
            qty_consumed = 0
            for price in line.prices.all().order_by('id'):
                if qty_consumed == qty_to_consume:
                    # We've accounted for the asked-for quantity: we're done
                    # 我们已经考虑了数量问题：我们已经完成了。
                    break

                qty_available = price.quantity - qty_to_skip
                if qty_available <= 0:
                    # Skip the whole quantity of this price instance
                    # 跳过此价格实例的全部数量
                    qty_to_skip -= price.quantity
                else:
                    # Need to account for some of this price instance and
                    # track how many we needed to skip and how many we settled
                    # for.
                    # 需要考虑一些价格实例，并跟踪我们需要跳过的数量以及我们确定的数量。
                    qty_to_include = min(
                        qty_to_consume - qty_consumed, qty_available)
                    total += qty_to_include * price.price_incl_tax
                    # There can't be any left to skip if we've included some in
                    # our total
                    # 如果我们在总数中包含了一些，那么就不会有任何遗漏
                    qty_to_skip = 0
                    qty_consumed += qty_to_include
        return total

    # Stock 库存
    # -----

    def are_stock_allocations_available(self, lines, line_quantities):
        """
        Check whether stock records still have enough stock to honour the
        requested allocations.

        Lines whose product doesn't track stock are disregarded, which means
        this method will return True if only non-stock-tracking-lines are
        passed.
        This means you can just throw all order lines to this method, without
        checking whether stock tracking is enabled or not.
        This is okay, as calling consume_stock_allocations() has no effect for
        non-stock-tracking lines.

        检查库存记录是否有足够的库存来满足所需的分配。
        产品不跟踪库存的行被忽略，这意味着如果只传递非库存跟踪行，此方法将返回True。
        这意味着您可以将所有订单行抛出到此方法，而无需检查是否启用了库存跟踪。
        这没关系，因为调用consume_stock_allocations（）对非库存跟踪行没有影响。
        """
        for line, qty in zip(lines, line_quantities):
            record = line.stockrecord
            if not record:
                return False
            if not record.can_track_allocations:
                continue
            if not record.is_allocation_consumption_possible(qty):
                return False
        return True

    def consume_stock_allocations(self, order, lines=None, line_quantities=None):
        """
        Consume the stock allocations for the passed lines.

        If no lines/quantities are passed, do it for all lines.

        消耗传递行的库存分配。
        如果没有传递行/数量，请对所有行执行。
        """
        if not lines:
            lines = order.lines.all()
        if not line_quantities:
            line_quantities = [line.quantity for line in lines]
        for line, qty in zip(lines, line_quantities):
            if line.stockrecord:
                line.stockrecord.consume_allocation(qty)

    def cancel_stock_allocations(self, order, lines=None, line_quantities=None):
        """
        Cancel the stock allocations for the passed lines.

        If no lines/quantities are passed, do it for all lines.

        取消传递的行的库存分配。
        如果没有传递行/数量，请对所有行执行。
        """
        if not lines:
            lines = order.lines.all()
        if not line_quantities:
            line_quantities = [line.quantity for line in lines]
        for line, qty in zip(lines, line_quantities):
            if line.stockrecord:
                line.stockrecord.cancel_allocation(qty)

    # Model instance creation 模型实例创建
    # -----------------------

    def create_shipping_event(self, order, event_type, lines, line_quantities,
                              **kwargs):
        reference = kwargs.get('reference', '')
        event = order.shipping_events.create(
            event_type=event_type, notes=reference)
        try:
            for line, quantity in zip(lines, line_quantities):
                event.line_quantities.create(
                    line=line, quantity=quantity)
        except exceptions.InvalidShippingEvent:
            event.delete()
            raise
        return event

    def create_payment_event(self, order, event_type, amount, lines=None,
                             line_quantities=None, **kwargs):
        reference = kwargs.get('reference', "")
        event = order.payment_events.create(
            event_type=event_type, amount=amount, reference=reference)
        if lines and line_quantities:
            for line, quantity in zip(lines, line_quantities):
                event.line_quantities.create(
                    line=line, quantity=quantity)
        return event

    def create_communication_event(self, order, event_type):
        return order.communication_events.create(event_type=event_type)

    def create_note(self, order, message, note_type='System'):
        return order.notes.create(
            message=message, note_type=note_type, user=self.user)
