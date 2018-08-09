import logging
from itertools import chain

from oscar.core.loading import get_class, get_model

logger = logging.getLogger('oscar.offers')
OfferApplications = get_class('offer.results', 'OfferApplications')


# 报价应用错误
class OfferApplicationError(Exception):
    pass


# 填充器
class Applicator(object):

    def apply(self, basket, user=None, request=None):
        """
        Apply all relevant offers to the given basket.

        The request is passed too as sometimes the available offers
        are dependent on the user (eg session-based offers).

        将所有相关优惠应用于给定的购物篮。
        请求也被传递，因为有时可用的报价依赖于用户（例如基于会话的报价）。
        """
        offers = self.get_offers(basket, user, request)
        self.apply_offers(basket, offers)

    def apply_offers(self, basket, offers):
        applications = OfferApplications()
        for offer in offers:
            num_applications = 0
            # Keep applying the offer until either
            # (a) We reach the max number of applications for the offer.
            # (b) The benefit can't be applied successfully.
            # 持续报价，直到：
            # （a）我们达到了报价的最大数量。
            # （b）效益不能成功应用。
            while num_applications < offer.get_max_applications(basket.owner):
                result = offer.apply_benefit(basket)
                num_applications += 1
                if not result.is_successful:
                    break
                applications.add(offer, result)
                if result.is_final:
                    break

        # Store this list of discounts with the basket so it can be
        # rendered in templates
        # 将此折扣列表存储在购物篮中，以便可以在模板中呈现
        basket.offer_applications = applications

    def get_offers(self, basket, user=None, request=None):
        """
        Return all offers to apply to the basket.

        This method should be subclassed and extended to provide more
        sophisticated behaviour.  For instance, you could load extra offers
        based on the session or the user type.

        返回所有适用于购物篮的优惠。

        应该对此方法进行子类化和扩展，以提供更复杂的行为。 例如，您可以根据
        会话或用户类型加载额外的优惠。
        """
        site_offers = self.get_site_offers()
        basket_offers = self.get_basket_offers(basket, user)
        user_offers = self.get_user_offers(user)
        session_offers = self.get_session_offers(request)

        return list(sorted(chain(
            session_offers, basket_offers, user_offers, site_offers),
            key=lambda o: o.priority, reverse=True))

    def get_site_offers(self):
        """
        Return site offers that are available to all users
        返回所有用户都可以使用的网站优惠
        """
        ConditionalOffer = get_model('offer', 'ConditionalOffer')
        qs = ConditionalOffer.active.filter(offer_type=ConditionalOffer.SITE)
        # Using select_related with the condition/benefit ranges doesn't seem
        # to work.  I think this is because both the related objects have the
        # FK to range with the same name.
        # 使用带条件/效益范围的select_related似乎不起作用。 我认为这是因为两个相
        # 关对象都具有相同名称的FK范围。
        return qs.select_related('condition', 'benefit')

    def get_basket_offers(self, basket, user):
        """
        Return basket-linked offers such as those associated with a voucher
        code
        返回与购物篮相关的优惠，例如与优惠券代码相关的优惠
        """
        offers = []
        if not basket.id or not user:
            return offers

        for voucher in basket.vouchers.all():
            available_to_user, __ = voucher.is_available_to_user(user=user)
            if voucher.is_active() and available_to_user:
                basket_offers = voucher.offers.all()
                for offer in basket_offers:
                    offer.set_voucher(voucher)
                offers = list(chain(offers, basket_offers))
        return offers

    def get_user_offers(self, user):
        """
        Returns offers linked to this particular user.

        Eg: student users might get 25% off
        返回与此特定用户关联的商品。
        例如：学生用户可能会获得25％的折扣
        """
        return []

    def get_session_offers(self, request):
        """
        Returns temporary offers linked to the current session.

        Eg: visitors coming from an affiliate site get a 10% discount
        返回链接到当前会话的临时商品。
        例如：来自联盟网站的访客可享受10％的折扣
        """
        return []
