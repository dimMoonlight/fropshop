import re

from django.conf import settings


def strip_language_code(request):
    """
    When using Django's i18n_patterns, we need a language-neutral variant of
    the current URL to be able to use set_language to change languages.
    This naive approach strips the language code from the beginning of the URL
    and will likely fail if using translated URLs.

    当使用Django的i18n_patterns时，我们需要一个当前URL的语言中性变体才能
    使用set_language来更改语言。
    这种天真的方法从URL的开头剥离语言代码，如果使用翻译的URL，可能会失败。
    """
    path = request.path
    if settings.USE_I18N and hasattr(request, 'LANGUAGE_CODE'):
        return re.sub('^/%s/' % request.LANGUAGE_CODE, '/', path)
    return path


def metadata(request):
    """
    Add some generally useful metadata to the template context
    向模板上下文添加一些通常有用的元数据
    """
    return {'shop_name': settings.OSCAR_SHOP_NAME,
            'shop_tagline': settings.OSCAR_SHOP_TAGLINE,
            'homepage_url': settings.OSCAR_HOMEPAGE,
            'language_neutral_url_path': strip_language_code(request),
            # Fallback to old settings name for backwards compatibility
            # 回退到旧设置名称以实现向后兼容性
            'use_less': (getattr(settings, 'OSCAR_USE_LESS', None) or
                         getattr(settings, 'USE_LESS', False)),
            'google_analytics_id': (getattr(settings, 'OSCAR_GOOGLE_ANALYTICS_ID', None) or
                                    getattr(settings, 'GOOGLE_ANALYTICS_ID', None))}
