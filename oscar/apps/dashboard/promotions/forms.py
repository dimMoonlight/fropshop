from django import forms
from django.conf import settings
from django.utils.translation import gettext_lazy as _

from oscar.apps.promotions.conf import PROMOTION_CLASSES
from oscar.core.loading import get_class, get_classes
from oscar.forms.fields import ExtendedURLField

HandPickedProductList, RawHTML, SingleProduct, PagePromotion, OrderedProduct \
    = get_classes('promotions.models',
                  ['HandPickedProductList', 'RawHTML', 'SingleProduct',
                   'PagePromotion', 'OrderedProduct'])
ProductSelect = get_class('dashboard.catalogue.widgets', 'ProductSelect')


# 促销形式选择
class PromotionTypeSelectForm(forms.Form):
    choices = []
    for klass in PROMOTION_CLASSES:
        choices.append((klass.classname(), klass._meta.verbose_name))
    promotion_type = forms.ChoiceField(choices=tuple(choices),
                                       label=_("Promotion type"))


# 原始HTML表单
class RawHTMLForm(forms.ModelForm):
    class Meta:
        model = RawHTML
        fields = ['name', 'body']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['body'].widget.attrs['class'] = "no-widget-init"


# 单一产品表格
class SingleProductForm(forms.ModelForm):
    class Meta:
        model = SingleProduct
        fields = ['name', 'product', 'description']
        widgets = {'product': ProductSelect}


# 手工挑选的产品清单表格
class HandPickedProductListForm(forms.ModelForm):
    class Meta:
        model = HandPickedProductList
        fields = ['name', 'description', 'link_url', 'link_text']


# 订购产品表格
class OrderedProductForm(forms.ModelForm):
    class Meta:
        model = OrderedProduct
        fields = ['list', 'product', 'display_order']
        widgets = {
            'product': ProductSelect,
        }


# 页面推广表格
class PagePromotionForm(forms.ModelForm):
    page_url = ExtendedURLField(label=_("URL"))
    position = forms.CharField(
        widget=forms.Select(choices=settings.OSCAR_PROMOTION_POSITIONS),
        label=_("Position"),
        help_text=_("Where in the page this content block will appear"))

    class Meta:
        model = PagePromotion
        fields = ['position', 'page_url']

    def clean_page_url(self):
        page_url = self.cleaned_data.get('page_url')
        if not page_url:
            return page_url

        if page_url.startswith('http'):
            raise forms.ValidationError(
                _("Content blocks can only be linked to internal URLs"))

        if page_url.startswith('/') and not page_url.endswith('/'):
            page_url += '/'

        return page_url
