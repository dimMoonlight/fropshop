import logging

from django.conf import settings
from django.contrib.auth import login as auth_login
from django.contrib.auth import authenticate
from django.contrib.sites.shortcuts import get_current_site

from oscar.apps.customer.signals import user_registered
from oscar.core.compat import get_user_model
from oscar.core.loading import get_class, get_model

# 用户
User = get_user_model()
# 通讯事件类型
CommunicationEventType = get_model('customer', 'CommunicationEventType')
# 调度员
Dispatcher = get_class('customer.utils', 'Dispatcher')
# 记录仪
logger = logging.getLogger('oscar.customer')


# 混入页面标题
class PageTitleMixin(object):
    """
    Passes page_title and active_tab into context, which makes it quite useful
    for the accounts views.

    Dynamic page titles are possible by overriding get_page_title.

    将page_title和active_tab传递到上下文中，这使得它对帐户视图非常有用。

    通过覆盖get_page_title可以实现动态页面标题。
    """
    page_title = None
    active_tab = None

    # Use a method that can be overridden and customised
    # 使用可以覆盖和自定义的方法
    def get_page_title(self):
        return self.page_title

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.setdefault('page_title', self.get_page_title())
        ctx.setdefault('active_tab', self.active_tab)
        return ctx


# 注册用户
class RegisterUserMixin(object):
    communication_type_code = 'REGISTRATION'

    def register_user(self, form):
        """
        Create a user instance and send a new registration email (if configured
        to).
        创建用户实例并发送新的注册电子邮件（如果已配置）。
        """
        user = form.save()

        # Raise signal robustly (we don't want exceptions to crash the request
        # handling).
        # 有力地提高信号（我们不希望异常崩溃请求处理）。
        user_registered.send_robust(
            sender=self, request=self.request, user=user)

        if getattr(settings, 'OSCAR_SEND_REGISTRATION_EMAIL', True):
            self.send_registration_email(user)

        # We have to authenticate before login
        # 我们必须在登录前进行身份验证。
        try:
            user = authenticate(
                username=user.email,
                password=form.cleaned_data['password1'])
        except User.MultipleObjectsReturned:
            # Handle race condition where the registration request is made
            # multiple times in quick succession.  This leads to both requests
            # passing the uniqueness check and creating users (as the first one
            # hasn't committed when the second one runs the check).  We retain
            # the first one and deactivate the dupes.
            # 处理快速连续多次登记请求的竞争条件。 这导致两个请求都通过唯
            # 一性检查并创建用户（因为第一个请求在第二个运行检查时未提
            # 交）。 我们保留第一个并停用欺骗。
            logger.warning(
                'Multiple users with identical email address and password'
                'were found. Marking all but one as not active.')
            # 找到具有相同电子邮件地址和密码的多个用户。 标记除一个以外的所有活动。

            # As this section explicitly deals with the form being submitted
            # twice, this is about the only place in Oscar where we don't
            # ignore capitalisation when looking up an email address.
            # We might otherwise accidentally mark unrelated users as inactive
            # 由于本节明确处理了两次提交的表单，因此这是奥斯卡唯一一个在
            # 查找电子邮件地址时不会忽略大写的地方。 否则我们可能会意外
            # 地将不相关的用户标记为非活动状
            users = User.objects.filter(email=user.email)
            user = users[0]
            for u in users[1:]:
                u.is_active = False
                u.save()

        auth_login(self.request, user)

        return user

    def send_registration_email(self, user):
        code = self.communication_type_code
        ctx = {'user': user,
               'site': get_current_site(self.request)}
        messages = CommunicationEventType.objects.get_and_render(
            code, ctx)
        if messages and messages['body']:
            Dispatcher().dispatch_user_messages(user, messages)
