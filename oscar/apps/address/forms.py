from django import forms
from django.conf import settings

from oscar.core.loading import get_model
from oscar.forms.mixins import PhoneNumberMixin

UserAddress = get_model('address', 'useraddress')

# 抽象地址形式（生成地址形式类)
class AbstractAddressForm(forms.ModelForm):

    def __init__(self, *args, **kwargs):
        """
        Set fields in OSCAR_REQUIRED_ADDRESS_FIELDS as required.
        根据需要在 OSCAR_REQUIRED_ADDRESS_FIELDS  字段中设置字段。
        """
        super().__init__(*args, **kwargs)
        field_names = (set(self.fields) &
                       set(settings.OSCAR_REQUIRED_ADDRESS_FIELDS))
        for field_name in field_names:
            self.fields[field_name].required = True

# 抽象用户地址形式(生成用户地址形式类)
class UserAddressForm(PhoneNumberMixin, AbstractAddressForm):

    class Meta:
        model = UserAddress
        fields = [
            'title', 'first_name', 'last_name',
            'line1', 'line2', 'line3', 'line4',
            'state', 'postcode', 'country',
            'phone_number', 'notes',
        ]

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.user = user
