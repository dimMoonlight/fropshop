# -*- coding: utf-8 -*-
from django.contrib import messages
from django.core.exceptions import (
    MultipleObjectsReturned, ObjectDoesNotExist, PermissionDenied)
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.generic import (
    CreateView, DeleteView, FormView, ListView, UpdateView, View)

from oscar.core.loading import get_class, get_model
from oscar.core.utils import redirect_to_referrer, safe_referrer

WishList = get_model('wishlists', 'WishList')
Line = get_model('wishlists', 'Line')
Product = get_model('catalogue', 'Product')
WishListForm = get_class('wishlists.forms', 'WishListForm')
LineFormset = get_class('wishlists.formsets', 'LineFormset')
PageTitleMixin = get_class('customer.mixins', 'PageTitleMixin')


# 愿望清单列表视图
class WishListListView(PageTitleMixin, ListView):
    context_object_name = active_tab = "wishlists"
    template_name = 'customer/wishlists/wishlists_list.html'
    page_title = _('Wish Lists')

    def get_queryset(self):
        return self.request.user.wishlists.all()


# 愿望清单详细信息视图
class WishListDetailView(PageTitleMixin, FormView):
    """
    This view acts as a DetailView for a wish list and allows updating the
    quantities of products.

    It is implemented as FormView because it's easier to adapt a FormView to
    display a product then adapt a DetailView to handle form validation.

    此视图充当愿望清单的DetailView，并允许更新产品数量。
    它实现为FormView，因为它更容易调整FormView以显示产品，然后调整DetailView以
    处理表单验证。
    """
    template_name = 'customer/wishlists/wishlists_detail.html'
    active_tab = "wishlists"
    form_class = LineFormset

    # 调度
    def dispatch(self, request, *args, **kwargs):
        self.object = self.get_wishlist_or_404(kwargs['key'], request.user)
        return super().dispatch(request, *args, **kwargs)

    def get_wishlist_or_404(self, key, user):
        wishlist = get_object_or_404(WishList, key=key)
        if wishlist.is_allowed_to_see(user):
            return wishlist
        else:
            raise Http404

    def get_page_title(self):
        return self.object.name

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['instance'] = self.object
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['wishlist'] = self.object
        other_wishlists = self.request.user.wishlists.exclude(
            pk=self.object.pk)
        ctx['other_wishlists'] = other_wishlists
        return ctx

    def form_valid(self, form):
        for subform in form:
            if subform.cleaned_data['quantity'] <= 0:
                subform.instance.delete()
            else:
                subform.save()
        messages.success(self.request, _('Quantities updated.'))
        return redirect('customer:wishlists-detail', key=self.object.key)


# 愿望清单创建视图
class WishListCreateView(PageTitleMixin, CreateView):
    """
    Create a new wishlist

    If a product ID is assed as a kwargs, then this product will be added to
    the wishlist.
    创建一个新的愿望清单
    如果产品ID与kwargs相同，则此产品将添加到心愿单中。
    """
    model = WishList
    template_name = 'customer/wishlists/wishlists_form.html'
    active_tab = "wishlists"
    page_title = _('Create a new wish list')
    form_class = WishListForm
    product = None

    # 调度
    def dispatch(self, request, *args, **kwargs):
        if 'product_pk' in kwargs:
            try:
                self.product = Product.objects.get(pk=kwargs['product_pk'])
            except ObjectDoesNotExist:
                messages.error(
                    request, _("The requested product no longer exists"))
                return redirect('wishlists-create')
        return super().dispatch(
            request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['product'] = self.product
        return ctx

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        wishlist = form.save()
        if self.product:
            wishlist.add(self.product)
            msg = _("Your wishlist has been created and '%(name)s "
                    "has been added") \
                % {'name': self.product.get_title()}
        else:
            msg = _("Your wishlist has been created")
        messages.success(self.request, msg)
        return redirect(wishlist.get_absolute_url())


# 愿望清单使用产品视图创建
class WishListCreateWithProductView(View):
    """
    Create a wish list and immediately add a product to it
    创建愿望清单并立即向其添加产品
    """

    def post(self, request, *args, **kwargs):
        product = get_object_or_404(Product, pk=kwargs['product_pk'])
        wishlists = request.user.wishlists.all()
        if len(wishlists) == 0:
            wishlist = request.user.wishlists.create()
        else:
            # This shouldn't really happen but we default to using the first
            # wishlist for a user if one already exists when they make this
            # request.
            # 这不应该发生，但我们默认使用第一个愿望清单，如果用户在提出此请求时已存在。
            wishlist = wishlists[0]
        wishlist.add(product)
        messages.success(
            request, _("%(title)s has been added to your wishlist") % {
                'title': product.get_title()})
        return redirect_to_referrer(request, wishlist.get_absolute_url())


# 愿望清单更新视图
class WishListUpdateView(PageTitleMixin, UpdateView):
    model = WishList
    template_name = 'customer/wishlists/wishlists_form.html'
    active_tab = "wishlists"
    form_class = WishListForm
    context_object_name = 'wishlist'

    def get_page_title(self):
        return self.object.name

    def get_object(self, queryset=None):
        return get_object_or_404(WishList, owner=self.request.user,
                                 key=self.kwargs['key'])

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_success_url(self):
        messages.success(
            self.request, _("Your '%s' wishlist has been updated")
            % self.object.name)
        return reverse('customer:wishlists-list')


# 愿望清单删除视图
class WishListDeleteView(PageTitleMixin, DeleteView):
    model = WishList
    template_name = 'customer/wishlists/wishlists_delete.html'
    active_tab = "wishlists"

    def get_page_title(self):
        return _('Delete %s') % self.object.name

    def get_object(self, queryset=None):
        return get_object_or_404(WishList, owner=self.request.user,
                                 key=self.kwargs['key'])

    def get_success_url(self):
        messages.success(
            self.request, _("Your '%s' wish list has been deleted")
            % self.object.name)
        return reverse('customer:wishlists-list')


# 愿望清单添加产品
class WishListAddProduct(View):
    """
    Adds a product to a wish list.

    - If the user doesn't already have a wishlist then it will be created for
      them.
    - If the product is already in the wish list, its quantity is increased.

    将产品添加到愿望列表中。
    - 如果用户还没有一个愿望列表，那么它将为他们创建。
    - 如果产品已经在愿望列表中，它的数量就增加了。
    """

    def dispatch(self, request, *args, **kwargs):
        self.product = get_object_or_404(Product, pk=kwargs['product_pk'])
        self.wishlist = self.get_or_create_wishlist(request, *args, **kwargs)
        return super().dispatch(request)

    def get_or_create_wishlist(self, request, *args, **kwargs):
        if 'key' in kwargs:
            wishlist = get_object_or_404(
                WishList, key=kwargs['key'], owner=request.user)
        else:
            wishlists = request.user.wishlists.all()[:1]
            if not wishlists:
                return request.user.wishlists.create()
            wishlist = wishlists[0]

        if not wishlist.is_allowed_to_edit(request.user):
            raise PermissionDenied
        return wishlist

    def get(self, request, *args, **kwargs):
        # This is nasty as we shouldn't be performing write operations on a GET
        # request.  It's only included as the UI of the product detail page
        # allows a wishlist to be selected from a dropdown.
        # 这是令人讨厌的，因为我们不应该在GET请求上执行写操作。它只包含在产品
        # 细节页面的UI中，可以从下拉菜单中选择一个愿望列表。
        return self.add_product()

    def post(self, request, *args, **kwargs):
        return self.add_product()

    def add_product(self):
        self.wishlist.add(self.product)
        msg = _("'%s' was added to your wish list.") % self.product.get_title()
        messages.success(self.request, msg)
        return redirect_to_referrer(
            self.request, self.product.get_absolute_url())


# 混合线
class LineMixin(object):
    """
    Handles fetching both a wish list and a product
    Views using this mixin must be passed two keyword arguments:

    * key: The key of a wish list
    * line_pk: The primary key of the wish list line

    or

    * product_pk: The primary key of the product

    通过使用MIXIN处理两个关键字参数，获取两个关键字参数的意愿列表和产品视图：


    """

    def fetch_line(self, user, wishlist_key, line_pk=None, product_pk=None):
        self.wishlist = WishList._default_manager.get(
            owner=user, key=wishlist_key)
        if line_pk is not None:
            self.line = self.wishlist.lines.get(pk=line_pk)
        else:
            self.line = self.wishlist.lines.get(product_id=product_pk)
        self.product = self.line.product


# 愿望清单删除产品
class WishListRemoveProduct(LineMixin, PageTitleMixin, DeleteView):
    template_name = 'customer/wishlists/wishlists_delete_product.html'
    active_tab = "wishlists"

    def get_page_title(self):
        return _('Remove %s') % self.object.get_title()

    def get_object(self, queryset=None):
        self.fetch_line(
            self.request.user, self.kwargs['key'],
            self.kwargs.get('line_pk'), self.kwargs.get('product_pk'))
        return self.line

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['wishlist'] = self.wishlist
        ctx['product'] = self.product
        return ctx

    def get_success_url(self):
        msg = _("'%(title)s' was removed from your '%(name)s' wish list") % {
            'title': self.line.get_title(),
            'name': self.wishlist.name}
        messages.success(self.request, msg)

        # We post directly to this view on product pages; and should send the
        # user back there if that was the case
        # 我们直接在产品页上张贴此视图；如果情况是这样，则应该将用户发送回那里。
        referrer = safe_referrer(self.request, '')
        if (referrer and self.product and
                self.product.get_absolute_url() in referrer):
            return referrer
        else:
            return reverse(
                'customer:wishlists-detail', kwargs={'key': self.wishlist.key})


# 愿望清单移动产品到另一个愿望清单
class WishListMoveProductToAnotherWishList(LineMixin, View):

    def dispatch(self, request, *args, **kwargs):
        try:
            self.fetch_line(request.user, kwargs['key'],
                            line_pk=kwargs['line_pk'])
        except (ObjectDoesNotExist, MultipleObjectsReturned):
            raise Http404
        return super().dispatch(
            request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        to_wishlist = get_object_or_404(
            WishList, owner=request.user, key=kwargs['to_key'])

        if to_wishlist.lines.filter(product=self.line.product).count() > 0:
            msg = _("Wish list '%(name)s' already containing '%(title)s'") % {
                'title': self.product.get_title(),
                'name': to_wishlist.name}
            messages.error(self.request, msg)
        else:
            self.line.wishlist = to_wishlist
            self.line.save()

            msg = _("'%(title)s' moved to '%(name)s' wishlist") % {
                'title': self.product.get_title(),
                'name': to_wishlist.name}
            messages.success(self.request, msg)

        default_url = reverse(
            'customer:wishlists-detail', kwargs={'key': self.wishlist.key})
        return redirect_to_referrer(self.request, default_url)
