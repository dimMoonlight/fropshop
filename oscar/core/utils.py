import datetime
import logging
import re
import unicodedata

from django.conf import settings
from django.shortcuts import redirect, resolve_url
from django.template.defaultfilters import date as date_filter
from django.utils.http import is_safe_url
from django.utils.module_loading import import_string
from django.utils.text import slugify as django_slugify
from django.utils.timezone import get_current_timezone, is_naive, make_aware


SLUGIFY_RE = re.compile(r'[^\w\s-]', re.UNICODE)


def cautious_slugify(value):
    """
    Convert a string to ASCII exactly as Django's slugify does, with the exception
    that any non-ASCII alphanumeric characters (that cannot be ASCIIfied under Unicode
    normalisation) are escaped into codes like 'u0421' instead of being deleted entirely.
    This ensures that the result of slugifying e.g. Cyrillic text will not be an empty
    string, and can thus be safely used as an identifier (albeit not a human-readable one).

    cautious_slugify was copied from Wagtail:
    <https://github.com/wagtail/wagtail/blob/8b420b9/wagtail/core/utils.py>

    Copyright (c) 2014-present Torchbox Ltd and individual contributors.
    Released under the BSD 3-clause "New" or "Revised" License
    <https://github.com/wagtail/wagtail/blob/8b420b9/LICENSE>

    Date: 2018-06-15

    正如Django的slugify所做的那样，将字符串转换为ASCII，但任何非ASCII字母数字字符（在Unicode规
    范化下不能被ASCII化）都会转义为“u0421”之类的代码，而不是完全删除。
    这确保了例如slugifying的结果。 西里尔文本不是空字符串，因此可以安全地用作标识符（尽管不是人类可读的标识符）。

    从Wagtail复制了cautious_slugify：
    <https://github.com/wagtail/wagtail/blob/8b420b9/wagtail/core/utils.py>
    版权所有（c）2014-present Torchbox Ltd和个人贡献者。
    根据BSD 3条款“New”或“Revised”许可发布
    <https://github.com/wagtail/wagtail/blob/8b420b9/LICENSE>

    Date: 2018-06-15
    """
    # Normalize the string to decomposed unicode form. This causes accented Latin
    # characters to be split into 'base character' + 'accent modifier'; the latter will
    # be stripped out by the regexp, resulting in an ASCII-clean character that doesn't
    # need to be escaped
    # 将字符串规范化为分解的unicode形式。 这导致重音拉丁字符被分成'基本字符'+'重音修饰
    # 符'; 后者将被正则表达式删除，从而产生一个不需要转义的ASCII-clean字符
    value = unicodedata.normalize('NFKD', value)

    # Strip out characters that aren't letterlike, underscores or hyphens,
    # using the same regexp that slugify uses. This ensures that non-ASCII non-letters
    # (e.g. accent modifiers, fancy punctuation) get stripped rather than escaped
    # 使用与slugify使用相同的正则表达式删除不是字母，下划线或连字符的字符。 这可以确保
    # 非ASCII非字母（例如重音修饰符，花式标点符号）被剥离而不是转义
    value = SLUGIFY_RE.sub('', value)

    # Encode as ASCII, escaping non-ASCII characters with backslashreplace, then convert
    # back to a unicode string (which is what slugify expects)
    # 编码为ASCII，使用backslashreplace转义非ASCII字符，然后转换回unicode字符串
    # （这是slugify期望的）
    value = value.encode('ascii', 'backslashreplace').decode('ascii')

    # Pass to slugify to perform final conversion (whitespace stripping, applying
    # mark_safe); this will also strip out the backslashes from the 'backslashreplace'
    # conversion
    # 通过slugify进行最终转换（空白剥离，应用mark_safe）; 这也将
    # 从'backslashreplace'转换中去掉反斜杠
    return django_slugify(value)


def default_slugifier(value, allow_unicode=False):
    """
    Oscar's default slugifier function. When unicode is allowed
    it uses Django's slugify function, otherwise it uses cautious_slugify.
    奥斯卡的默认推土机功能。 当允许unicode时，它使用Django的slugify函数，否则
    使用cautious_slugify。
    """
    if allow_unicode:
        return django_slugify(value, allow_unicode=True)
    else:
        return cautious_slugify(value)


def slugify(value):
    """
    Slugify a string

    The OSCAR_SLUG_FUNCTION can be set with a dotted path to the slug
    function to use, defaults to 'oscar.core.utils.default_slugifier'.

    OSCAR_SLUG_MAP can be set of a dictionary of target:replacement pairs

    OSCAR_SLUG_BLACKLIST can be set to a iterable of words to remove after
    the slug is generated; though it will not reduce a slug to zero length.

    Slugify一个字符串
    可以使用要使用的slug函数的虚线路径设置OSCAR_SLUG_FUNCTION，默认为'oscar.core.utils.default_slugifier'。
    OSCAR_SLUG_MAP可以设置目标：替换对的字典
    OSCAR_SLUG_BLACKLIST可以设置为在生成slug后删除的可迭代单词; 虽然它不会将一个slug减少到零长度。
    """
    value = str(value)

    # Re-map some strings to avoid important characters being stripped.  Eg
    # remap 'c++' to 'cpp' otherwise it will become 'c'.
    # 重新映射一些字符串以避免重要字符被剥离。 例如，将'c ++'重新映射为'cpp'，否则它将变为'c'。
    for k, v in settings.OSCAR_SLUG_MAP.items():
        value = value.replace(k, v)

    slugifier = import_string(settings.OSCAR_SLUG_FUNCTION)
    slug = slugifier(value, allow_unicode=settings.OSCAR_SLUG_ALLOW_UNICODE)

    # Remove stopwords from slug
    # 从slug中删除停用词
    for word in settings.OSCAR_SLUG_BLACKLIST:
        slug = slug.replace(word + '-', '')
        slug = slug.replace('-' + word, '')

    return slug


def format_datetime(dt, format=None):
    """
    Takes an instance of datetime, converts it to the current timezone and
    formats it as a string. Use this instead of
    django.core.templatefilters.date, which expects localtime.

    获取datetime的实例，将其转换为当前时区并将其格式化为字符串。 使用它代
    替django.core.templatefilters.date，它需要localtime。

    :param format: Common will be settings.DATETIME_FORMAT or
                   settings.DATE_FORMAT, or the resp. shorthands
                   ('DATETIME_FORMAT', 'DATE_FORMAT')
    """
    if is_naive(dt):
        localtime = make_aware(dt, get_current_timezone())
        logging.warning(
            "oscar.core.utils.format_datetime received native datetime")
    else:
        localtime = dt.astimezone(get_current_timezone())
    return date_filter(localtime, format)


def datetime_combine(date, time):
    """
    Timezone aware version of `datetime.datetime.combine`
    时区感知版本的`datetime.datetime.combine`
    """
    return make_aware(
        datetime.datetime.combine(date, time), get_current_timezone())


def safe_referrer(request, default):
    """
    Takes the request and a default URL. Returns HTTP_REFERER if it's safe
    to use and set, and the default URL otherwise.

    The default URL can be a model with get_absolute_url defined, a urlname
    or a regular URL

    接受请求和默认URL。 如果可以安全使用和设置，则返回HTTP_REFERER，否则返回默认URL。
    默认URL可以是定义了get_absolute_url的模型，urlname或常规URL
    """
    referrer = request.META.get('HTTP_REFERER')
    if referrer and is_safe_url(referrer, request.get_host()):
        return referrer
    if default:
        # Try to resolve. Can take a model instance, Django URL name or URL.
        # 试着解决。 可以采用模型实例，Django URL名称或URL。
        return resolve_url(default)
    else:
        # Allow passing in '' and None as default
        # 允许传入''和None作为默认值
        return default


def redirect_to_referrer(request, default):
    """
    Takes request.META and a default URL to redirect to.

    Returns a HttpResponseRedirect to HTTP_REFERER if it exists and is a safe
    URL; to the default URL otherwise.

    使用request.META和重定向到的默认URL。
    返回HTTP_REFERER的HttpResponseRedirect（如果存在且是安全URL）; 否则为默认URL。
    """
    return redirect(safe_referrer(request, default))


def get_default_currency():
    """
    For use as the default value for currency fields.  Use of this function
    prevents Django's core migration engine from interpreting a change to
    OSCAR_DEFAULT_CURRENCY as something it needs to generate a migration for.

    用作货币字段的默认值。 使用此函数可以防止Django的核心迁移引擎将
    对OSCAR_DEFAULT_CURRENCY的更改解释为生成迁移所需的内容。
    """
    return settings.OSCAR_DEFAULT_CURRENCY
