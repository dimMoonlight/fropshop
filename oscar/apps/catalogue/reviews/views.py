from django.conf import settings
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, DetailView, ListView, View

from oscar.apps.catalogue.reviews.signals import review_added
from oscar.core.loading import get_classes, get_model
from oscar.core.utils import redirect_to_referrer

ProductReviewForm, VoteForm, SortReviewsForm = get_classes(
    'catalogue.reviews.forms',
    ['ProductReviewForm', 'VoteForm', 'SortReviewsForm'])

Vote = get_model('reviews', 'vote')
ProductReview = get_model('reviews', 'ProductReview')
Product = get_model('catalogue', 'product')


# 创建产品评论
class CreateProductReview(CreateView):
    template_name = "catalogue/reviews/review_form.html"
    model = ProductReview
    product_model = Product
    form_class = ProductReviewForm
    view_signal = review_added

    def dispatch(self, request, *args, **kwargs):
        self.product = get_object_or_404(
            self.product_model, pk=kwargs['product_pk'])
        # check permission to leave review
        # 检查允许留下评论
        if not self.product.is_review_permitted(request.user):
            if self.product.has_review_by(request.user):
                # 您已经评论过此产品
                message = _("You have already reviewed this product!")
            else:
                # 您无法对此产品发表评论
                message = _("You can't leave a review for this product.")
            messages.warning(self.request, message)
            return redirect(self.product.get_absolute_url())

        return super().dispatch(
            request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['product'] = self.product
        return context

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['product'] = self.product
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        self.send_signal(self.request, response, self.object)
        return response

    def get_success_url(self):
        messages.success(
            self.request, _("Thank you for reviewing this product"))
        # 感谢您对本商品做出评价
        return self.product.get_absolute_url()

    def send_signal(self, request, response, review):
        self.view_signal.send(sender=self, review=review, user=request.user,
                              request=request, response=response)


# 产品评论详情
class ProductReviewDetail(DetailView):
    template_name = "catalogue/reviews/review_detail.html"
    context_object_name = 'review'
    model = ProductReview

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['product'] = get_object_or_404(
            Product, pk=self.kwargs['product_pk'])
        return context

# 添加投票视图
class AddVoteView(View):
    """
    Simple view for voting on a review.

    We use the URL path to determine the product and review and use a 'delta'
    POST variable to indicate it the vote is up or down.

    简单的投票评论视图。
    我们使用URL路径来确定产品并查看并使用'delta'POST变量来指示投票是向上还是向下。
    """

    def post(self, request, *args, **kwargs):
        product = get_object_or_404(Product, pk=self.kwargs['product_pk'])
        review = get_object_or_404(ProductReview, pk=self.kwargs['pk'])

        form = VoteForm(review, request.user, request.POST)
        if form.is_valid():
            if form.is_up_vote:
                review.vote_up(request.user)
            elif form.is_down_vote:
                review.vote_down(request.user)
            messages.success(request, _("Thanks for voting!"))
        else:
            for error_list in form.errors.values():
                for msg in error_list:
                    messages.error(request, msg)
        return redirect_to_referrer(request, product.get_absolute_url())


# 产品评论清单
class ProductReviewList(ListView):
    """
    Browse reviews for a product
    浏览产品评论
    """
    template_name = 'catalogue/reviews/review_list.html'
    context_object_name = "reviews"
    model = ProductReview
    product_model = Product
    paginate_by = settings.OSCAR_REVIEWS_PER_PAGE

    def get_queryset(self):
        qs = self.model.objects.approved().filter(product=self.kwargs['product_pk'])
        self.form = SortReviewsForm(self.request.GET)
        if self.form.is_valid():
            sort_by = self.form.cleaned_data['sort_by']
            if sort_by == SortReviewsForm.SORT_BY_RECENCY:
                return qs.order_by('-date_created')
        return qs.order_by('-score')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['product'] = get_object_or_404(
            self.product_model, pk=self.kwargs['product_pk'])
        context['form'] = self.form
        return context