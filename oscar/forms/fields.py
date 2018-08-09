from django.forms import TextInput, fields

from oscar.core import validators


class ExtendedURLField(fields.URLField):
    """
    Custom field similar to URLField type field, however also accepting and
    validating local relative URLs, ie. '/product/'
    自定义字段类似于URLField类型字段，但也接受和验证本地相对URL，即。 '/产品/'
    """
    default_validators = []
    # Django 1.6 renders URLInput as <input type=url>, which causes some
    # browsers to require the input to be a valid absolute URL. As relative
    # URLS are allowed for ExtendedURLField, we must set it to TextInput
    # Django 1.6将URLInput呈现为<input type = url>，这会导致某些浏览器要求输入为有效的绝对URL。
    #  由于ExtendedURLField允许相对URL，我们必须将其设置为TextInput
    widget = TextInput

    def __init__(self, max_length=None, min_length=None, *args, **kwargs):
        super(fields.URLField, self).__init__(*args, **kwargs)
        self.validators.append(validators.ExtendedURLValidator())

    def to_python(self, value):
        # We need to avoid having 'http' inserted at the start of
        # every value so that local URLs are valid.
        # 我们需要避免在每个值的开头插入“http”，以便本地URL有效。
        if value and value.startswith('/'):
            return value
        return super().to_python(value)
