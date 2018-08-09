import datetime

from django import forms
from django.utils.translation import gettext_lazy as _

from oscar.core.loading import get_model
from oscar.forms import widgets

# 条件要约
ConditionalOffer = get_model('offer', 'ConditionalOffer')
# 条件
Condition = get_model('offer', 'Condition')
# 效益
Benefit = get_model('offer', 'Benefit')


# 元数据表格
class MetaDataForm(forms.ModelForm):
    class Meta:
        model = ConditionalOffer
        fields = ('name', 'description',)


# 限制形式
class RestrictionsForm(forms.ModelForm):

    start_datetime = forms.DateTimeField(
        widget=widgets.DateTimePickerInput(),
        label=_("Start date"), required=False)
    end_datetime = forms.DateTimeField(
        widget=widgets.DateTimePickerInput(),
        label=_("End date"), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        today = datetime.date.today()
        self.fields['start_datetime'].initial = today

    class Meta:
        model = ConditionalOffer
        fields = ('start_datetime', 'end_datetime',
                  'max_basket_applications', 'max_user_applications',
                  'max_global_applications', 'max_discount',
                  'priority', 'exclusive')

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data['start_datetime']
        end = cleaned_data['end_datetime']
        if start and end and end < start:
            raise forms.ValidationError(_(
                "The end date must be after the start date"))
        return cleaned_data


# 条件形式
class ConditionForm(forms.ModelForm):
    custom_condition = forms.ChoiceField(
        required=False,
        label=_("Custom condition"), choices=())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        custom_conditions = Condition.objects.all().exclude(
            proxy_class=None)
        if len(custom_conditions) > 0:
            # Initialise custom_condition field
            # 初始化custom_condition字段
            choices = [(c.id, str(c)) for c in custom_conditions]
            choices.insert(0, ('', ' --------- '))
            self.fields['custom_condition'].choices = choices
            condition = kwargs.get('instance')
            if condition:
                self.fields['custom_condition'].initial = condition.id
        else:
            # No custom conditions and so the type/range/value fields
            # are no longer optional
            # 没有自定义条件，因此类型/范围/值字段不再是可选的。
            for field in ('type', 'range', 'value'):
                self.fields[field].required = True

    class Meta:
        model = Condition
        fields = ['range', 'type', 'value']

    def clean(self):
        data = super().clean()

        # Check that either a condition has been entered or a custom condition
        # has been chosen
        # 检查是否已输入条件或已选择自定义条件
        if not any(data.values()):
            raise forms.ValidationError(
                _("Please either choose a range, type and value OR "
                  "select a custom condition"))

        if not data['custom_condition']:
            if not data.get('range', None):
                raise forms.ValidationError(
                    _("A range is required"))

        return data

    def save(self, *args, **kwargs):
        # We don't save a new model if a custom condition has been chosen,
        # we simply return the instance that has been chosen
        # 如果选择了自定义条件，我们不保存新模型，我们只返回已选择的实例
        if self.cleaned_data['custom_condition']:
            return Condition.objects.get(
                id=self.cleaned_data['custom_condition'])
        return super().save(*args, **kwargs)


# 效益形式
class BenefitForm(forms.ModelForm):
    custom_benefit = forms.ChoiceField(
        required=False,
        label=_("Custom incentive"), choices=())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        custom_benefits = Benefit.objects.all().exclude(
            proxy_class=None)
        if len(custom_benefits) > 0:
            # Initialise custom_benefit field
            # 初始化客户利益字段
            choices = [(c.id, str(c)) for c in custom_benefits]
            choices.insert(0, ('', ' --------- '))
            self.fields['custom_benefit'].choices = choices
            benefit = kwargs.get('instance')
            if benefit:
                self.fields['custom_benefit'].initial = benefit.id
        else:
            # No custom benefit and so the type fields
            # are no longer optional
            # 没有自定义的好处，因此类型字段不再是可选的
            self.fields['type'].required = True

    class Meta:
        model = Benefit
        fields = ['range', 'type', 'value', 'max_affected_items']

    def clean(self):
        data = super().clean()

        # Check that either a benefit has been entered or a custom benfit
        # has been chosen
        # 检查是否已输入效益或已选择自定义功能
        if not any(data.values()):
            raise forms.ValidationError(
                _("Please either choose a range, type and value OR "
                  "select a custom incentive"))
            # 请选择范围，类型和价值或选择自定义奖励

        if data['custom_benefit']:
            if data.get('range') or data.get('type') or data.get('value'):
                raise forms.ValidationError(
                    _("No other options can be set if you are using a "
                      "custom incentive"))
                # 如果您使用自定义激励，则无法设置其他选项

        return data

    def save(self, *args, **kwargs):
        # We don't save a new model if a custom benefit has been chosen,
        # we simply return the instance that has been chosen
        # 如果选择了自定义权益，我们不保存新模型，我们只返回已选择的实例
        if self.cleaned_data['custom_benefit']:
            return Benefit.objects.get(
                id=self.cleaned_data['custom_benefit'])
        return super().save(*args, **kwargs)


# 报价搜索表
class OfferSearchForm(forms.Form):
    name = forms.CharField(required=False, label=_("Offer name"))
    is_active = forms.BooleanField(required=False, label=_("Is active?"))
