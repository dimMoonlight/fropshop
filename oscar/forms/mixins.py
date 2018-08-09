import phonenumbers
from django import forms
from django.core import validators
from django.utils.translation import gettext_lazy as _
from phonenumber_field.phonenumber import PhoneNumber


class PhoneNumberMixin(object):
    """Validation mixin for forms with a phone numbers, and optionally a country.

    It tries to validate the phone numbers, and on failure tries to validate
    them using a hint (the country provided), and treating it as a local number.

    Specify which fields to treat as phone numbers by specifying them in
    `phone_number_fields`, a dictionary of fields names and default kwargs
    for instantiation of the field.

    验证mixin表示带有电话号码的表单，以及可选的国家/地区。
    它尝试验证电话号码，并在失败时尝试使用提示（提供的国家/地区）验证它们，并将其视为本地号码。
    通过在`phone_number_fields`中指定要将哪些字段视为电话号码，字段名称字典和默认kwargs用于实例化字段。
    """
    country = None
    region_code = None
    # Since this mixin will be used with `ModelForms`, names of phone number
    # fields should match names of the related Model field
    # 由于此mixin将与`ModelForms`一起使用，因此电话号码字段的名称应与相关Model字段的名称匹配
    phone_number_fields = {
        'phone_number': {
            'required': False,
            'help_text': '',
            'max_length': 32,
            'label': _('Phone number')
        },
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # We can't use the PhoneNumberField here since we want validate the
        # phonenumber based on the selected country as a fallback when a local
        # number is entered. We add the fields in the init since on Python 2
        # using forms.Form as base class results in errors when using this
        # class as mixin.
        # 我们不能在这里使用PhoneNumberField，因为我们想要在输入本地号码时根据所选国家/地区
        # 验证电话号码作为后备。 我们在Python 2中使用forms.Form作为基类在init中添加字段会导
        # 致在将此类用作mixin时出错。

        # If the model field already exists, copy existing properties from it
        # 如果模型字段已存在，则从中复制现有属性
        for field_name, field_kwargs in self.phone_number_fields.items():
            for key in field_kwargs:
                try:
                    field_kwargs[key] = getattr(self.fields[field_name], key)
                except (KeyError, AttributeError):
                    pass

            self.fields[field_name] = forms.CharField(**field_kwargs)

    def get_country(self):
        # If the form data contains valid country information, we use that.
        # 如果表单数据包含有效的国家/地区信息，我们会使用它。
        if hasattr(self, 'cleaned_data') and 'country' in self.cleaned_data:
            return self.cleaned_data['country']
        # Oscar hides the field if there's only one country. Then (and only
        # then!) we can consider a country on the model instance.
        # 如果只有一个国家，奥斯卡会隐藏这个领域。 然后（只有那时！）我们可以考虑模型实例上的国家。
        elif 'country' not in self.fields and hasattr(self.instance, 'country'):
            return self.instance.country

    def set_country_and_region_code(self):
        # Try hinting with the shipping country if we can determine one.
        # 如果我们可以确定一个，请尝试与运输国家联系。
        self.country = self.get_country()
        if self.country:
            self.region_code = self.country.iso_3166_1_a2

    def clean_phone_number_field(self, field_name):
        number = self.cleaned_data.get(field_name)

        # Empty
        if number in validators.EMPTY_VALUES:
            return ''

        # Check for an international phone format
        # 检查国际电话格式
        try:
            phone_number = PhoneNumber.from_string(number)
        except phonenumbers.NumberParseException:

            if not self.region_code:
                # There is no shipping country, not a valid international number
                # 没有运输国家/地区，不是有效的国际号码
                self.add_error(
                    field_name,
                    _('This is not a valid international phone format.'))
                return number

            # The PhoneNumber class does not allow specifying
            # the region. So we drop down to the underlying phonenumbers
            # library, which luckily allows parsing into a PhoneNumber
            # instance.
            # PhoneNumber类不允许指定区域。 所以我们下载到底层的phonenumbers库，幸运的是
            # 允许解析为PhoneNumber实例。
            try:
                phone_number = PhoneNumber.from_string(number,
                                                       region=self.region_code)
                if not phone_number.is_valid():
                    self.add_error(
                        field_name,
                        _('This is not a valid local phone format for %s.')
                        % self.country)
            except phonenumbers.NumberParseException:
                # Not a valid local or international phone number
                # 不是有效的本地或国际电话号码
                self.add_error(
                    field_name,
                    _('This is not a valid local or international phone format.'))
                return number

        return phone_number

    def clean(self):
        self.set_country_and_region_code()
        cleaned_data = super().clean()
        for field_name in self.phone_number_fields:
            cleaned_data[field_name] = self.clean_phone_number_field(field_name)
        return cleaned_data
