import csv

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured

from oscar.core.loading import get_model


# A setting that can be used in foreign key declarations
# 可在外键声明中使用的设置
AUTH_USER_MODEL = getattr(settings, 'AUTH_USER_MODEL', 'auth.User')
try:
    AUTH_USER_APP_LABEL, AUTH_USER_MODEL_NAME = AUTH_USER_MODEL.rsplit('.', 1)
except ValueError:
    raise ImproperlyConfigured("AUTH_USER_MODEL must be of the form"
                               " 'app_label.model_name'")


def get_user_model():
    """
    Return the User model. Doesn't require the app cache to be fully
    initialised.

    This used to live in compat to support both Django 1.4's fixed User model
    and custom user models introduced thereafter.
    Support for Django 1.4 has since been dropped in Oscar, but our
    get_user_model remains because code relies on us annotating the _meta class
    with the additional fields, and other code might rely on it as well.

    返回用户模型。 不要求应用程序缓存完全初始化。
    过去常常用于支持Django 1.4的固定用户模型和之后引入的自定义用户模型。
    从那以后，我们已经在Oscar中删除了对Django 1.4的支持，但我们的get_user_model仍
    然存在，因为代码依赖于我们用附加字段注释_meta类，而其他代码也可能依赖它。
    """

    try:
        model = get_model(AUTH_USER_APP_LABEL, AUTH_USER_MODEL_NAME)
    except LookupError:
        # Convert exception to an ImproperlyConfigured exception for
        # backwards compatibility with previous Oscar versions and the
        # original get_user_model method in Django.
        # 将异常转换为ImproperlyConfigured异常，以便向后兼容以前的Oscar版本
        # 和Django中的原始get_user_model方法。
        raise ImproperlyConfigured(
            "AUTH_USER_MODEL refers to model '%s' that has not been installed"
            % settings.AUTH_USER_MODEL)

    # Test if user model has any custom fields and add attributes to the _meta
    # class
    # 测试用户模型是否具有任何自定义字段并向_meta类添加属性
    core_fields = set([f.name for f in User._meta.fields])
    model_fields = set([f.name for f in model._meta.fields])
    new_fields = model_fields.difference(core_fields)
    model._meta.has_additional_fields = len(new_fields) > 0
    model._meta.additional_fields = new_fields

    return model


def existing_user_fields(fields):
    """
    Starting with Django 1.6, the User model can be overridden  and it is no
    longer safe to assume the User model has certain fields. This helper
    function assists in writing portable forms Meta.fields definitions
    when those contain fields on the User model

    Usage:
    class UserForm(forms.Form):
        ...
        class Meta:
            # won't break if first_name is not defined on User model
            fields = existing_user_fields(['first_name', 'last_name'])

    从Django 1.6开始，可以覆盖用户模型，并且假设用户模型具有某些字段已不再安全。
     当辅助函数包含用户模型上的字段时，此辅助函数可帮助编写可移植表
     单Meta.fields定义
     用法：
     class UserForm（forms.Form）：
         ...
         class Meta：
         如果未在用户模型上定义first_name，＃将不会中断
         fields = existing_user_fields(['first_name', 'last_name'])
    """
    user_fields = get_user_model()._meta.fields
    user_field_names = [field.name for field in user_fields]
    return [field for field in fields if field in user_field_names]


# Python3 compatibility layer
# Python3兼容层

"""
Unicode compatible wrapper for CSV reader and writer that abstracts away
differences between Python 2 and 3. A package like unicodecsv would be
preferable, but it's not Python 3 compatible yet.

Code from http://python3porting.com/problems.html
Changes:
- Classes renamed to include CSV.
- Unused 'codecs' import is dropped.
- Added possibility to specify an open file to the writer to send as response
  of a view
  
用于CSV读取器和写入器的Unicode兼容包装器，它抽象出Python 2和3之间的差异。
像unicodecsv这样的软件包会更好，但它还不兼容Python 3。 
来自http://python3porting.com/problems.html的代码 
变化：
- 重命名的类包含CSV。
- 删除未使用的“编解码器”导入。
- 增加了为作者指定打开文件以作为视图响应发送的可能性
"""


class UnicodeCSVReader:
    def __init__(self, filename, dialect=csv.excel,
                 encoding="utf-8", **kw):
        self.filename = filename
        self.dialect = dialect
        self.encoding = encoding
        self.kw = kw

    def __enter__(self):
        self.f = open(self.filename, 'rt', encoding=self.encoding, newline='')
        self.reader = csv.reader(self.f, dialect=self.dialect,
                                 **self.kw)
        return self

    def __exit__(self, type, value, traceback):
        self.f.close()

    def next(self):
        return next(self.reader)

    __next__ = next

    def __iter__(self):
        return self


class UnicodeCSVWriter:
    """
    Python 2 3 compatible CSV writer. Supports two modes:
    * Writing to an open file or file-like object:
      writer = UnicodeCSVWriter(open_file=your_file)
      ...
      your_file.close()
    * Writing to a new file:
      with UnicodeCSVWriter(filename=filename) as writer:
          ...

     Python 2 3兼容的CSV编写器。 支持两种模式：
    * 写入打开的文件或类文件对象：
    writer = UnicodeCSVWriter(open_file=your_file)
        ...
      your_file.close()
    * 写入新文件：
      with UnicodeCSVWriter(filename=filename) as writer:
         ...
    """
    def __init__(self, filename=None, open_file=None, dialect=csv.excel,
                 encoding="utf-8", **kw):
        if filename is open_file is None:
            raise ImproperlyConfigured(
                "You need to specify either a filename or an open file")
        self.filename = filename
        self.f = open_file
        self.dialect = dialect
        self.encoding = encoding
        self.kw = kw
        self.writer = None

        if self.f:
            self.add_bom(self.f)

    def __enter__(self):
        assert self.filename is not None
        self.f = open(self.filename, 'wt', encoding=self.encoding, newline='')
        self.add_bom(self.f)
        return self

    def __exit__(self, type, value, traceback):
        assert self.filename is not None
        if self.filename is not None:
            self.f.close()

    def add_bom(self, f):
        # If encoding is UTF-8, insert a Byte Order Mark at the start of the
        # file for compatibility with MS Excel.
        # 如果编码为UTF-8，请在文件的开头插入字节顺序标记以与MS Excel兼容。
        if (self.encoding == 'utf-8'
                and getattr(settings, 'OSCAR_CSV_INCLUDE_BOM', False)):
            self.f.write('\ufeff')

    def writerow(self, row):
        if self.writer is None:
            self.writer = csv.writer(self.f, dialect=self.dialect, **self.kw)
        self.writer.writerow(list(row))

    def writerows(self, rows):
        for row in rows:
            self.writerow(row)
