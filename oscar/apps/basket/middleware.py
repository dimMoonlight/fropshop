from django.conf import settings
from django.contrib import messages
from django.core.signing import BadSignature, Signer
from django.utils.functional import SimpleLazyObject, empty
from django.utils.translation import gettext_lazy as _

from oscar.core.loading import get_class, get_model

Applicator = get_class('offer.applicator', 'Applicator')
Basket = get_model('basket', 'basket')
Selector = get_class('partner.strategy', 'Selector')

selector = Selector()


class BasketMiddleware:

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Keep track of cookies that need to be deleted (which can only be done
        # when we're processing the response instance).
        # 跟踪需要删除的Cookie（只能在处理响应实例时完成）
        request.cookies_to_delete = []

        # Load stock/price strategy and assign to request (it will later be
        # assigned to the basket too).
        # 加载库存/价格策略，并分配给请求（稍后将分配给篮子）。
        strategy = selector.strategy(request=request, user=request.user)
        request.strategy = strategy

        # We lazily load the basket so use a private variable to hold the
        # cached instance.
        # 我们懒惰地加载购物篮，所以使用一个私有变量来保存缓存实例。
        request._basket_cache = None

        def load_full_basket():
            """
            Return the basket after applying offers.
            申请后退还购物篮
            """
            basket = self.get_basket(request)
            basket.strategy = request.strategy
            self.apply_offers_to_basket(request, basket)

            return basket

        def load_basket_hash():
            """
            Load the basket and return the basket hash

            Note that we don't apply offers or check that every line has a
            stockrecord here.

            加载购物篮，并返回购物篮记录，我们不申请提供或检查，每一行有一个库存记录在这里。
            """
            basket = self.get_basket(request)
            if basket.id:
                return self.get_basket_hash(basket.id)

        # Use Django's SimpleLazyObject to only perform the loading work
        # when the attribute is accessed.
        # 使用Django's SimpleLazyObject只在访问属性时执行加载工作
        request.basket = SimpleLazyObject(load_full_basket)
        request.basket_hash = SimpleLazyObject(load_basket_hash)

        response = self.get_response(request)
        return self.process_response(request, response)

    def process_response(self, request, response):
        # Delete any surplus cookies
        # 删除多余的cookies
        cookies_to_delete = getattr(request, 'cookies_to_delete', [])
        for cookie_key in cookies_to_delete:
            response.delete_cookie(cookie_key)

        if not hasattr(request, 'basket'):
            return response

        # If the basket was never initialized we can safely return
        # 如果购物篮从未被初始化，我们可以安全返回。
        if (isinstance(request.basket, SimpleLazyObject)
                and request.basket._wrapped is empty):
            return response

        cookie_key = self.get_cookie_key(request)
        # Check if we need to set a cookie. If the cookies is already available
        # but is set in the cookies_to_delete list then we need to re-set it.
        # 检查我们是否需要设置cookie.如果Cookies已经可用，但在cookies_to_delete列表中设置，
        # 那么我们需要重新设置它。
        has_basket_cookie = (
            cookie_key in request.COOKIES
            and cookie_key not in cookies_to_delete)

        # If a basket has had products added to it, but the user is anonymous
        # then we need to assign it to a cookie
        # 如果一个购物篮已经添加了产品，但是用户是匿名的，那么我们需要把它分配给cookie。
        if (request.basket.id and not request.user.is_authenticated
                and not has_basket_cookie):
            cookie = self.get_basket_hash(request.basket.id)
            response.set_cookie(
                cookie_key, cookie,
                max_age=settings.OSCAR_BASKET_COOKIE_LIFETIME,
                secure=settings.OSCAR_BASKET_COOKIE_SECURE, httponly=True)
        return response

    def get_cookie_key(self, request):
        """
        Returns the cookie name to use for storing a cookie basket.

        The method serves as a useful hook in multi-site scenarios where
        different baskets might be needed.

        返回用于存储cookie篮子的cookie名称。该方法在多站点场景中充当有用的HOOK，
        可能需要不同的购物篮。
        """
        # hook 挂钩，windows 下的‘中断'系统机制
        return settings.OSCAR_BASKET_COOKIE_OPEN

    def process_template_response(self, request, response):
        if hasattr(response, 'context_data'):
            if response.context_data is None:
                response.context_data = {}
            if 'basket' not in response.context_data:
                response.context_data['basket'] = request.basket
            else:
                # Occasionally, a view will want to pass an alternative basket
                # to be rendered.  This can happen as part of checkout
                # processes where the submitted basket is frozen when the
                # customer is redirected to another site (eg PayPal).  When the
                # customer returns and we want to show the order preview
                # template, we need to ensure that the frozen basket gets
                # rendered (not request.basket).  We still keep a reference to
                # the request basket (just in case).
                # 偶尔，一个视图会想通过另一个购物篮来渲染。这可以作为结帐过程的一部分，
                # 当客户被重定向到另一个站点（如PayPal）时，提交的购物篮被冻结。
                # 当客户返回并且我们想要显示订单预览模板时，我们需要确保冻结的购物篮
                # 得到渲染（而不是请求购物篮）。我们仍然保持对请求购物篮的引用（以防万一）。
                response.context_data['request_basket'] = request.basket
        return response

    # Helper methods 辅助方法

    def get_basket(self, request):
        """
        Return the open basket for this request
        为这个请求返回打开购物篮
        """
        if request._basket_cache is not None:
            return request._basket_cache

        num_baskets_merged = 0
        manager = Basket.open
        cookie_key = self.get_cookie_key(request)
        cookie_basket = self.get_cookie_basket(cookie_key, request, manager)

        if hasattr(request, 'user') and request.user.is_authenticated:
            # Signed-in user: if they have a cookie basket too, it means
            # that they have just signed in and we need to merge their cookie
            # basket into their user basket, then delete the cookie.
            # 登录用户：如果他们有cookie购物篮，这意味着他们刚刚签到，
            # 我们需要将他们的cookie购物篮合并到他们的用户购物篮中，然后删除cookie。
            try:
                basket, __ = manager.get_or_create(owner=request.user)
            except Basket.MultipleObjectsReturned:
                # Not sure quite how we end up here with multiple baskets.
                # We merge them and create a fresh one
                # 不确定我们是如何用多个购物篮结束的。我们合并它们并创建一个新的。
                old_baskets = list(manager.filter(owner=request.user))
                basket = old_baskets[0]
                for other_basket in old_baskets[1:]:
                    self.merge_baskets(basket, other_basket)
                    num_baskets_merged += 1

            # Assign user onto basket to prevent further SQL queries when
            # basket.owner is accessed.
            # 将用户分配到购物篮上，以防止在购物篮下访问其他SQL查询。
            basket.owner = request.user

            if cookie_basket:
                self.merge_baskets(basket, cookie_basket)
                num_baskets_merged += 1
                request.cookies_to_delete.append(cookie_key)

        elif cookie_basket:
            # Anonymous user with a basket tied to the cookie
            # 匿名用户有一个购物篮绑在cookie上
            basket = cookie_basket
        else:
            # Anonymous user with no basket - instantiate a new basket
            # instance.  No need to save yet.
            # 匿名用户没有购物篮 - 实例化一个新的购物篮实例。 不需要保存。
            basket = Basket()

        # Cache basket instance for the during of this request
        # 此请求期间的缓存购物篮实例
        request._basket_cache = basket

        if num_baskets_merged > 0:
            messages.add_message(request, messages.WARNING,
                                 _("We have merged a basket from a previous session. Its contents "
                                   "might have changed."))

        return basket

    def merge_baskets(self, master, slave):
        """
        Merge one basket into another.

        This is its own method to allow it to be overridden

        把一个购物篮合并成另一个购物篮。这是允许它被重写的自己的方法。
        """
        master.merge(slave, add_quantities=False)

    def get_cookie_basket(self, cookie_key, request, manager):
        """
        Looks for a basket which is referenced by a cookie.

        If a cookie key is found with no matching basket, then we add
        it to the list to be deleted.

        寻找一个由cookie引用的购物篮。
        如果发现没有匹配购物篮的Cookie密钥，那么我们将其添加到要删除的列表中。
        """
        basket = None
        if cookie_key in request.COOKIES:
            basket_hash = request.COOKIES[cookie_key]
            try:
                basket_id = Signer().unsign(basket_hash)
                basket = Basket.objects.get(pk=basket_id, owner=None,
                                            status=Basket.OPEN)
            except (BadSignature, Basket.DoesNotExist):
                request.cookies_to_delete.append(cookie_key)
        return basket

    def apply_offers_to_basket(self, request, basket):
        if not basket.is_empty:
            Applicator().apply(basket, request.user, request)

    def get_basket_hash(self, basket_id):
        return Signer().sign(basket_id)
