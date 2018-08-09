from django.db import models
from django.utils.timezone import now


class ActiveOfferManager(models.Manager):
    """
    For searching/creating offers within their date range
    用于在日期范围内搜索/创建商品
    """
    def get_queryset(self):
        cutoff = now()
        return super().get_queryset().filter(
            models.Q(end_datetime__gte=cutoff) | models.Q(end_datetime=None),
            models.Q(start_datetime__lte=cutoff) | models.Q(start_datetime=None),
        ).filter(status=self.model.OPEN)


# 可浏览范围管理器
class BrowsableRangeManager(models.Manager):
    """
    For searching only ranges which have the "is_browsable" flag set to True.
    # 仅搜索“is_browsable”标志设置为True的范围。
    """
    def get_queryset(self):
        return super().get_queryset().filter(
            is_public=True)
