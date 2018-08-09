from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Count, Sum
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.utils.translation import pgettext_lazy

from oscar.apps.catalogue.reviews.utils import get_default_review_status
from oscar.core import validators
from oscar.core.compat import AUTH_USER_MODEL
from oscar.core.loading import get_class


ProductReviewQuerySet = get_class('catalogue.reviews.managers', 'ProductReviewQuerySet')


# 抽象产品评论
class AbstractProductReview(models.Model):
    """
    A review of a product

    Reviews can belong to a user or be anonymous.

    对产品的评论
    评论可以属于用户或匿名。
    """

    product = models.ForeignKey(
        'catalogue.Product', related_name='reviews', null=True,
        on_delete=models.CASCADE)

    # Scores are between 0 and 5
    # 分数在0 到5之间
    SCORE_CHOICES = tuple([(x, x) for x in range(0, 6)])
    score = models.SmallIntegerField(_("Score"), choices=SCORE_CHOICES)

    title = models.CharField(
        verbose_name=pgettext_lazy("Product review title", "Title"),
        max_length=255, validators=[validators.non_whitespace])

    body = models.TextField(_("Body"))

    # User information.
    # 用户信息。
    user = models.ForeignKey(
        AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.CASCADE,
        related_name='reviews')

    # Fields to be completed if user is anonymous
    # 如果用户是匿名的，则要填写的字段
    name = models.CharField(
        pgettext_lazy("Anonymous reviewer name", "Name"),
        max_length=255, blank=True)
    email = models.EmailField(_("Email"), blank=True)
    homepage = models.URLField(_("URL"), blank=True)

    FOR_MODERATION, APPROVED, REJECTED = 0, 1, 2
    STATUS_CHOICES = (
        (FOR_MODERATION, _("Requires moderation")),
        (APPROVED, _("Approved")),
        (REJECTED, _("Rejected")),
    )

    status = models.SmallIntegerField(
        _("Status"), choices=STATUS_CHOICES, default=get_default_review_status)

    # Denormalised vote totals
    # 非规范化投票总数
    total_votes = models.IntegerField(
        _("Total Votes"), default=0)  # upvotes + down votes # 投票
    delta_votes = models.IntegerField(
        _("Delta Votes"), default=0, db_index=True)  # upvotes - down votes # 投票

    date_created = models.DateTimeField(auto_now_add=True)

    # Managers 管理员
    objects = ProductReviewQuerySet.as_manager()

    class Meta:
        abstract = True
        app_label = 'reviews'
        ordering = ['-delta_votes', 'id']
        unique_together = (('product', 'user'),)
        verbose_name = _('Product review')
        verbose_name_plural = _('Product reviews')

    def get_absolute_url(self):
        kwargs = {
            'product_slug': self.product.slug,
            'product_pk': self.product.id,
            'pk': self.id
        }
        return reverse('catalogue:reviews-detail', kwargs=kwargs)

    def __str__(self):
        return self.title

    # 清除
    def clean(self):
        self.title = self.title.strip()
        self.body = self.body.strip()
        if not self.user and not (self.name and self.email):
            raise ValidationError(
                _("Anonymous reviews must include a name and an email"))

    def vote_up(self, user):
        self.votes.create(user=user, delta=AbstractVote.UP)

    def vote_down(self, user):
        self.votes.create(user=user, delta=AbstractVote.DOWN)

    # 保存
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.product.update_rating()

    # 删除
    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        if self.product is not None:
            self.product.update_rating()

    # Properties 属性

    @property
    def is_anonymous(self):  # 匿名
        return self.user is None

    @property
    def pending_moderation(self):  # 等待审核
        return self.status == self.FOR_MODERATION

    @property
    def is_approved(self):  # 被批准
        return self.status == self.APPROVED

    @property
    def is_rejected(self):  # 被拒绝了
        return self.status == self.REJECTED

    @property
    def has_votes(self):  # 有票
        return self.total_votes > 0

    @property
    def num_up_votes(self):
        """Returns the total up votes"""
        # 返回总票数
        return int((self.total_votes + self.delta_votes) / 2)

    @property
    def num_down_votes(self):
        """Returns the total down votes"""
        return int((self.total_votes - self.delta_votes) / 2)

    # 评论者姓名
    @property
    def reviewer_name(self):
        if self.user:
            name = self.user.get_full_name()
            return name if name else _('anonymous')
        else:
            return self.name

    # Helpers 助手

    # 更新总数量
    def update_totals(self):
        """
        Update total and delta votes
        """
        result = self.votes.aggregate(
            score=Sum('delta'), total_votes=Count('id'))
        self.total_votes = result['total_votes'] or 0
        self.delta_votes = result['score'] or 0
        self.save()

    # 可以用户投票
    def can_user_vote(self, user):
        """
        Test whether the passed user is allowed to vote on this
        review
        """
        # 测试是否允许传递的用户对此评论进行投票
        if not user.is_authenticated:
            return False, _("Only signed in users can vote")
        vote = self.votes.model(review=self, user=user, delta=1)
        try:
            vote.full_clean()
        except ValidationError as e:
            return False, "%s" % e
        return True, ""


# 抽象投票
class AbstractVote(models.Model):
    """
    Records user ratings as yes/no vote.

    * Only signed-in users can vote.
    * Each user can vote only once.

    将用户评分记录为是/否投票。
    * 只有已登录的用户才能投票。
    * 每个用户只能投票一次。
    """
    review = models.ForeignKey(
        'reviews.ProductReview',
        on_delete=models.CASCADE,
        related_name='votes')
    user = models.ForeignKey(
        AUTH_USER_MODEL,
        related_name='review_votes',
        on_delete=models.CASCADE)
    UP, DOWN = 1, -1
    VOTE_CHOICES = (
        (UP, _("Up")),
        (DOWN, _("Down"))
    )
    delta = models.SmallIntegerField(_('Delta'), choices=VOTE_CHOICES)
    date_created = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        app_label = 'reviews'
        ordering = ['-date_created']
        unique_together = (('user', 'review'),)
        verbose_name = _('Vote')
        verbose_name_plural = _('Votes')

    def __str__(self):
        return "%s vote for %s" % (self.delta, self.review)

    def clean(self):
        if not self.review.is_anonymous and self.review.user == self.user:
            raise ValidationError(_(
                "You cannot vote on your own reviews"))
        if not self.user.id:
            raise ValidationError(_(
                "Only signed-in users can vote on reviews"))
        previous_votes = self.review.votes.filter(user=self.user)
        if len(previous_votes) > 0:
            raise ValidationError(_(
                "You can only vote once on a review"))

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.review.update_totals()
