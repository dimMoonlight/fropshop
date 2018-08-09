from django.contrib import admin

from oscar.core.loading import get_model

# 用户地址管理
class UserAddressAdmin(admin.ModelAdmin):
    # 只读字段
    readonly_fields = ('num_orders_as_billing_address', 'num_orders_as_shipping_address')

# 国家管理器
class CountryAdmin(admin.ModelAdmin):
    list_display = [
        '__str__',
        'display_order'
    ]
    list_filter = [
        'is_shipping_country'
    ]
    search_fields = [
        'name',
        'printable_name',
        'iso_3166_1_a2',
        'iso_3166_1_a3'
    ]


admin.site.register(get_model('address', 'useraddress'), UserAddressAdmin)
admin.site.register(get_model('address', 'country'), CountryAdmin)
