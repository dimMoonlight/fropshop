from django import forms
from django.template import Template, TemplateSyntaxError
from django.utils.translation import gettext_lazy as _

from oscar.apps.customer.utils import normalise_email
from oscar.core.loading import get_model

CommunicationEventType = get_model('customer', 'CommunicationEventType')
Order = get_model('order', 'Order')


# 通信事件类型表单
class CommunicationEventTypeForm(forms.ModelForm):
    email_subject_template = forms.CharField(
        label=_("Email subject template"))
    email_body_template = forms.CharField(
        label=_("Email body text template"), required=True,
        widget=forms.widgets.Textarea(attrs={'class': 'plain'}))
    email_body_html_template = forms.CharField(
        label=_("Email body HTML template"), required=True,
        widget=forms.Textarea)

    preview_order_number = forms.CharField(
        label=_("Order number"), required=False)
    preview_email = forms.EmailField(label=_("Preview email"),
                                     required=False)

    def __init__(self, data=None, *args, **kwargs):
        self.show_preview = False
        self.send_preview = False
        if data:
            self.show_preview = 'show_preview' in data
            self.send_preview = 'send_preview' in data
        super().__init__(data, *args, **kwargs)

    # 验证模板
    def validate_template(self, value):
        try:
            Template(value)
        except TemplateSyntaxError as e:
            raise forms.ValidationError(str(e))

    # 邮件主题模板
    def clean_email_subject_template(self):
        subject = self.cleaned_data['email_subject_template']
        self.validate_template(subject)
        return subject

    # 邮件正文模板
    def clean_email_body_template(self):
        body = self.cleaned_data['email_body_template']
        self.validate_template(body)
        return body

    # 电子邮件体HTML模板
    def clean_email_body_html_template(self):
        body = self.cleaned_data['email_body_html_template']
        self.validate_template(body)
        return body

    # 预览订单号
    def clean_preview_order_number(self):
        number = self.cleaned_data['preview_order_number'].strip()
        if not self.instance.is_order_related():
            return number
        if not self.show_preview and not self.send_preview:
            return number
        try:
            self.preview_order = Order.objects.get(number=number)
        except Order.DoesNotExist:
            raise forms.ValidationError(_(
                "No order found with this number"))
        return number

    # 预览电子邮件
    def clean_preview_email(self):
        email = normalise_email(self.cleaned_data['preview_email'])
        if not self.send_preview:
            return email
        if not email:
            raise forms.ValidationError(_(
                "Please enter an email address"))
        return email

    # 获取预览上下文
    def get_preview_context(self):
        ctx = {}
        if hasattr(self, 'preview_order'):
            ctx['order'] = self.preview_order
        return ctx

    class Meta:
        model = CommunicationEventType
        fields = [
            'name', 'email_subject_template', 'email_body_template',
            'email_body_html_template', 'preview_order_number', 'preview_email'
        ]
