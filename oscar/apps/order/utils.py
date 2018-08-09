from decimal import Decimal as D

from django.conf import settings
from django.contrib.sites.models import Site
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from oscar.apps.order.signals import order_placed
from oscar.core.loading import get_model

from . import exceptions

Order = get_model('order', 'Order')
Line = get_model('order', 'Line')
OrderDiscount = get_model('order', 'OrderDiscount')


class OrderNumberGenerator(object):
    """
    Simple object for generating order numbers.

    We need this as the order number is often required for payment
    which takes place before the order model has been created.

    用于生成订单号的简单对象。
    我们需要这个，因为在创建订单模型之前付款通常需要订单号。
    """

    def order_number(self, basket):
        """
        Return an order number for a given basket
        返回给定购物篮的订单号
        """
        return 100000 + basket.id


class OrderCreator(object):
    """
    Places the order by writing out the various models
    通过写出各种型号来下订单
    """

    def place_order(self, basket, total,  # noqa (too complex (12))
                    shipping_method, shipping_charge, user=None,
                    shipping_address=None, billing_address=None,
                    order_number=None, status=None, request=None, **kwargs):
        """
        Placing an order involves creating all the relevant models based on the
        basket and session data.
        下订单涉及根据购物篮和会话数据创建所有相关模型。
        """
        if basket.is_empty:
            raise ValueError(_("Empty baskets cannot be submitted"))
        if not order_number:
            generator = OrderNumberGenerator()
            order_number = generator.order_number(basket)
        if not status and hasattr(settings, 'OSCAR_INITIAL_ORDER_STATUS'):
            status = getattr(settings, 'OSCAR_INITIAL_ORDER_STATUS')

        if Order._default_manager.filter(number=order_number).exists():
            raise ValueError(_("There is already an order with number %s")
                             % order_number)

        with transaction.atomic():

            # Ok - everything seems to be in order, let's place the order
            # 好的 - 一切似乎都井然有序，让我们下订单
            order = self.create_order_model(
                user, basket, shipping_address, shipping_method, shipping_charge,
                billing_address, total, order_number, status, request, **kwargs)
            for line in basket.all_lines():
                self.create_line_models(order, line)
                self.update_stock_records(line)

            for voucher in basket.vouchers.select_for_update():
                available_to_user, msg = voucher.is_available_to_user(user=user)
                if not voucher.is_active() or not available_to_user:
                    raise ValueError(msg)

            # Record any discounts associated with this order
            # 记录与此订单相关的任何折扣
            for application in basket.offer_applications:
                # Trigger any deferred benefits from offers and capture the
                # resulting message
                # 触发优惠中的任何延期优惠并捕获生成的消息
                application['message'] \
                    = application['offer'].apply_deferred_benefit(basket, order,
                                                                  application)
                # Record offer application results
                # 记录报价申请结果
                if application['result'].affects_shipping:
                    # Skip zero shipping discounts
                    # 跳过零运费折扣
                    shipping_discount = shipping_method.discount(basket)
                    if shipping_discount <= D('0.00'):
                        continue
                    # If a shipping offer, we need to grab the actual discount off
                    # the shipping method instance, which should be wrapped in an
                    # OfferDiscount instance.
                    # 如果是运费报价，我们需要从运输方法实例中获取实际折扣，该实例
                    # 应包含在OfferDiscount实例中。
                    application['discount'] = shipping_discount
                self.create_discount_model(order, application)
                self.record_discount(application)

            for voucher in basket.vouchers.all():
                self.record_voucher_usage(order, voucher, user)

        # Send signal for analytics to pick up
        # 发送分析信号 ？
        order_placed.send(sender=self, order=order, user=user)

        return order

    def create_order_model(self, user, basket, shipping_address,
                           shipping_method, shipping_charge, billing_address,
                           total, order_number, status, request=None, **extra_order_fields):
        """Create an order model. 创建订单模型"""
        order_data = {'basket': basket,
                      'number': order_number,
                      'currency': total.currency,
                      'total_incl_tax': total.incl_tax,
                      'total_excl_tax': total.excl_tax,
                      'shipping_incl_tax': shipping_charge.incl_tax,
                      'shipping_excl_tax': shipping_charge.excl_tax,
                      'shipping_method': shipping_method.name,
                      'shipping_code': shipping_method.code}
        if shipping_address:
            order_data['shipping_address'] = shipping_address
        if billing_address:
            order_data['billing_address'] = billing_address
        if user and user.is_authenticated:
            order_data['user_id'] = user.id
        if status:
            order_data['status'] = status
        if extra_order_fields:
            order_data.update(extra_order_fields)
        if 'site' not in order_data:
            order_data['site'] = Site._default_manager.get_current(request)
        order = Order(**order_data)
        order.save()
        return order

    def create_line_models(self, order, basket_line, extra_line_fields=None):
        """
        Create the batch line model.

        You can set extra fields by passing a dictionary as the
        extra_line_fields value

        创建批次行模型。
        您可以通过将字典作为extra_line_fields值传递来设置额外字段
        """
        product = basket_line.product
        stockrecord = basket_line.stockrecord
        if not stockrecord:
            raise exceptions.UnableToPlaceOrder(
                "Basket line #%d has no stockrecord" % basket_line.id)
        partner = stockrecord.partner
        line_data = {
            'order': order,
            # Partner details 伙伴详情
            'partner': partner,
            'partner_name': partner.name,
            'partner_sku': stockrecord.partner_sku,
            'stockrecord': stockrecord,
            # Product details 产品详情
            'product': product,
            'title': product.get_title(),
            'upc': product.upc,
            'quantity': basket_line.quantity,
            # Price details 价格细节
            'line_price_excl_tax':
            basket_line.line_price_excl_tax_incl_discounts,
            'line_price_incl_tax':
            basket_line.line_price_incl_tax_incl_discounts,
            'line_price_before_discounts_excl_tax':
            basket_line.line_price_excl_tax,
            'line_price_before_discounts_incl_tax':
            basket_line.line_price_incl_tax,
            # Reporting details 报告细节
            'unit_cost_price': stockrecord.cost_price,
            'unit_price_incl_tax': basket_line.unit_price_incl_tax,
            'unit_price_excl_tax': basket_line.unit_price_excl_tax,
            'unit_retail_price': stockrecord.price_retail,
            # Shipping details 送货细节
            'est_dispatch_date':
            basket_line.purchase_info.availability.dispatch_date
        }
        extra_line_fields = extra_line_fields or {}
        if hasattr(settings, 'OSCAR_INITIAL_LINE_STATUS'):
            if not (extra_line_fields and 'status' in extra_line_fields):
                extra_line_fields['status'] = getattr(
                    settings, 'OSCAR_INITIAL_LINE_STATUS')
        if extra_line_fields:
            line_data.update(extra_line_fields)

        order_line = Line._default_manager.create(**line_data)
        self.create_line_price_models(order, order_line, basket_line)
        self.create_line_attributes(order, order_line, basket_line)
        self.create_additional_line_models(order, order_line, basket_line)

        return order_line

    def update_stock_records(self, line):
        """
        Update any relevant stock records for this order line
        更新此订单行的所有相关库存记录
        """
        if line.product.get_product_class().track_stock:
            line.stockrecord.allocate(line.quantity)

    def create_additional_line_models(self, order, order_line, basket_line):
        """
        Empty method designed to be overridden.

        Some applications require additional information about lines, this
        method provides a clean place to create additional models that
        relate to a given line.

        设计为被覆盖的空方法。
        某些应用程序需要有关行的其他信息，此方法提供了一个干净的位置来创建
        与给定行相关的其他模型。
        """
        pass

    def create_line_price_models(self, order, order_line, basket_line):
        """
        Creates the batch line price models
        创建批次行价格模型
        """
        breakdown = basket_line.get_price_breakdown()
        for price_incl_tax, price_excl_tax, quantity in breakdown:
            order_line.prices.create(
                order=order,
                quantity=quantity,
                price_incl_tax=price_incl_tax,
                price_excl_tax=price_excl_tax)

    def create_line_attributes(self, order, order_line, basket_line):
        """
        Creates the batch line attributes.
        创建批次行属性。
        """
        for attr in basket_line.attributes.all():
            order_line.attributes.create(
                option=attr.option,
                type=attr.option.code,
                value=attr.value)

    def create_discount_model(self, order, discount):

        """
        Create an order discount model for each offer application attached to
        the basket.
        为附加到购物篮的每个商品申请创建订单折扣模型。
        """
        order_discount = OrderDiscount(
            order=order,
            message=discount['message'] or '',
            offer_id=discount['offer'].id,
            frequency=discount['freq'],
            amount=discount['discount'])
        result = discount['result']
        if result.affects_shipping:
            order_discount.category = OrderDiscount.SHIPPING
        elif result.affects_post_order:
            order_discount.category = OrderDiscount.DEFERRED
        voucher = discount.get('voucher', None)
        if voucher:
            order_discount.voucher_id = voucher.id
            order_discount.voucher_code = voucher.code
        order_discount.save()

    def record_discount(self, discount):
        discount['offer'].record_usage(discount)
        if 'voucher' in discount and discount['voucher']:
            discount['voucher'].record_discount(discount)

    def record_voucher_usage(self, order, voucher, user):
        """
        Updates the models that care about this voucher.
        更新关注此凭证的模型。
        """
        voucher.record_usage(order, user)
