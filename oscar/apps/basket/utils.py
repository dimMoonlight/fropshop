from collections import defaultdict

from django.contrib import messages
from django.template.loader import render_to_string

from oscar.core.loading import get_class

Applicator = get_class('offer.applicator', 'Applicator')


class BasketMessageGenerator(object):

    new_total_template_name = 'basket/messages/new_total.html'
    offer_lost_template_name = 'basket/messages/offer_lost.html'
    offer_gained_template_name = 'basket/messages/offer_gained.html'

    def get_new_total_messages(self, basket, include_buttons=True):
        new_total_messages = []
        # We use the 'include_buttons' parameter to determine whether to show the
        # 'Checkout now' buttons.  We don't want to show these on the basket page
        # 我们使用“include_buttons”来决定是否显示“现在结账”按钮。我们不想在购物篮上展示这些.
        msg = render_to_string(self.new_total_template_name,
                               {'basket': basket,
                                'include_buttons': include_buttons})
        new_total_messages.append((messages.INFO, msg))

        return new_total_messages

    #  得到要约丢失信息
    def get_offer_lost_messages(self, offers_before, offers_after):
        offer_messages = []
        for offer_id in set(offers_before).difference(offers_after):
            offer = offers_before[offer_id]
            msg = render_to_string(self.offer_lost_template_name, {'offer': offer})
            offer_messages.append((messages.WARNING, msg))
        return offer_messages

    # 得到要约增加信息
    def get_offer_gained_messages(self, offers_before, offers_after):
        offer_messages = []
        for offer_id in set(offers_after).difference(offers_before):
            offer = offers_after[offer_id]
            msg = render_to_string(self.offer_gained_template_name, {'offer': offer})
            offer_messages.append((messages.SUCCESS, msg))
        return offer_messages

    # 得到要约信息
    def get_offer_messages(self, offers_before, offers_after):
        offer_messages = []
        offer_messages.extend(self.get_offer_lost_messages(offers_before, offers_after))
        offer_messages.extend(self.get_offer_gained_messages(offers_before, offers_after))
        return offer_messages

    # 获得信息
    def get_messages(self, basket, offers_before, offers_after, include_buttons=True):
        messages = []
        messages.extend(self.get_offer_messages(offers_before, offers_after))
        messages.extend(self.get_new_total_messages(basket, include_buttons))
        return messages

    # 应用消息
    def apply_messages(self, request, offers_before):
        """
        Set flash messages triggered by changes to the basket
        设置由购物篮的变化触发的Flash消息
        """
        # Re-apply offers to see if any new ones are now available
        # 重新申请，看看是否有任何新的现在可用
        request.basket.reset_offer_applications()
        Applicator().apply(request.basket, request.user, request)
        offers_after = request.basket.applied_offers()

        for level, msg in self.get_messages(request.basket, offers_before, offers_after):
            messages.add_message(request, level, msg, extra_tags='safe noicon')


# 行要约用户
class LineOfferConsumer(object):
    """
    facade for marking basket lines as consumed by
    any or a specific offering.

    historically oscar marks a line as consumed if any
    offer is applied to it, but more complicated scenarios
    are possible if we mark the line as being consumed by
    specific offers.

    this allows combining i.e. multiple vouchers, vouchers
    with special session discounts, etc.

    用于标记购物篮行的正面，被任何或特定的商品所消耗。
    从历史上看，如果一条行被应用于奥斯卡，那么它就被消耗掉了，但是如果我们把这条行标记
    为特定的要约消耗，那么更复杂的场景是可能的。
    这允许合并i.e. multiple vouchers, vouchers with special session  discounts, etc.
    """

    def __init__(self, line):
        self.__line = line
        self.__offers = dict()
        self.__affected_quantity = 0
        self.__consumptions = defaultdict(int)

    # private 私有的
    def __cache(self, offer):
        self.__offers[offer.pk] = offer

    def __update_affected_quantity(self, quantity):
        available = int(self.__line.quantity - self.__affected_quantity)
        self.__affected_quantity += min(available, quantity)

    # public 公众的
    def consume(self, quantity, offer=None):
        """
        mark a basket line as consumed by an offer

        :param int quantity: the number of items on the line affected
        :param offer: the offer to mark the line
        :type offer: ConditionalOffer or None

        if offer is None, the specified quantity of items on this
        basket line is consumed for *any* offer, else only for the
        specified offer.

        在报价中标出购物篮行
        :参数 int量：受影响的项目数量
        : 参数 要约:要约的报价
        ： 类型 要约：有条件的要约或无
        """
        self.__update_affected_quantity(quantity)
        if offer:
            self.__cache(offer)
            available = self.available(offer)
            self.__consumptions[offer.pk] += min(available, quantity)

    # 消耗
    def consumed(self, offer=None):
        """
        check how many items on this line have been
        consumed by an offer

        :param offer: the offer to check
        :type offer: ConditionalOffer or None
        :return: the number of items marked as consumed
        :rtype: int

        if offer is not None, only the number of items marked
        with the specified ConditionalOffer are returned


        检查这条行上有多少项目被要约消耗掉了
        """
        if not offer:
            return self.__affected_quantity
        return int(self.__consumptions[offer.pk])

    def available(self, offer=None):
        """
        check how many items are available for offer

        :param offer: the offer to check
        :type offer: ConditionalOffer or None
        :return: the number of items available for offer
        :rtype: int

        检查可用的要约项目
        ：参数 要约：要约检验
        ：类型 要约：有条件的要约或无
        ：返回：可用的要约数
        ：rtype （relation type ）关系类型： int 整数
        """
        if offer:
            exclusive = any([x.exclusive for x in self.__offers.values()])
            exclusive |= bool(offer.exclusive)
        else:
            exclusive = True

        if exclusive:
            offer = None

        consumed = self.consumed(offer)
        return int(self.__line.quantity - consumed)
