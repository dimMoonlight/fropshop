from django.conf.urls import url
from django.contrib.auth.decorators import login_required

from oscar.core.application import Application
from oscar.core.loading import get_class


# 购物篮应用程序
class BasketApplication(Application):
    name = 'basket'
    summary_view = get_class('basket.views', 'BasketView')  # 概要视图
    saved_view = get_class('basket.views', 'SavedView')     # 保存视图
    add_view = get_class('basket.views', 'BasketAddView')   # 添加视图
    add_voucher_view = get_class('basket.views', 'VoucherAddView')  # 添加凭证视图
    remove_voucher_view = get_class('basket.views', 'VoucherRemoveView')  # 删除凭证视图

    # 获取网址
    def get_urls(self):
        urls = [
            url(r'^$', self.summary_view.as_view(), name='summary'),
            url(r'^add/(?P<pk>\d+)/$', self.add_view.as_view(), name='add'),
            url(r'^vouchers/add/$', self.add_voucher_view.as_view(),
                name='vouchers-add'),
            url(r'^vouchers/(?P<pk>\d+)/remove/$',
                self.remove_voucher_view.as_view(), name='vouchers-remove'),
            url(r'^saved/$', login_required(self.saved_view.as_view()),
                name='saved'),
        ]
        return self.post_process_urls(urls)


application = BasketApplication()
