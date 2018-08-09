from django.urls import reverse_lazy

from oscar.forms.widgets import MultipleRemoteSelect, RemoteSelect


# 产品选择
class ProductSelect(RemoteSelect):
    # Implemented as separate class instead of just calling
    # 实现单独的类而不是只调用
    # AjaxSelect(data_url=...) for overridability and backwards compatibility
    # AjaxSelect（data_url = ...）具有可覆盖性和向后兼容性
    lookup_url = reverse_lazy('dashboard:catalogue-product-lookup')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.attrs['class'] = 'select2 product-select'


# 产品选择倍数
class ProductSelectMultiple(MultipleRemoteSelect):
    # Implemented as separate class instead of just calling
    # 实现单独的类而不是只调用
    # AjaxSelect(data_url=...) for overridability and backwards compatibility
    # AjaxSelect（data_url = ...）具有可覆盖性和向后兼容性
    lookup_url = reverse_lazy('dashboard:catalogue-product-lookup')
