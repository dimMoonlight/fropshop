# -*- coding: utf-8 -*-

from django.conf import settings

if settings.OSCAR_DELETE_IMAGE_FILES:

    from oscar.core.loading import get_model

    from django.db import models
    from django.db.models.signals import post_delete

    from sorl import thumbnail
    from sorl.thumbnail.helpers import ThumbnailError

    ProductImage = get_model('catalogue', 'ProductImage')
    Category = get_model('catalogue', 'Category')

    def delete_image_files(sender, instance, **kwargs):
        """
        Deletes the original image, created thumbnails, and any entries
        in sorl's key-value store.
        删除原始图像，创建的缩略图以及sorl键值存储中的任何条目。
        """
        image_fields = (models.ImageField, thumbnail.ImageField)
        for field in instance._meta.fields:
            if isinstance(field, image_fields):
                # Make Django return ImageFieldFile instead of ImageField
                # 让Django返回ImageFieldFile而不是ImageField
                fieldfile = getattr(instance, field.name)
                try:
                    thumbnail.delete(fieldfile)
                except ThumbnailError:
                    pass

    # connect for all models with ImageFields - add as needed
    # 使用ImageFields连接所有型号 - 根据需要添加
    models_with_images = [ProductImage, Category]
    for sender in models_with_images:
        post_delete.connect(delete_image_files, sender=sender)
