from django.contrib.auth.backends import ModelBackend
from django.core.exceptions import ImproperlyConfigured

from oscar.apps.customer.utils import normalise_email
from oscar.core.compat import get_user_model

User = get_user_model()

if hasattr(User, 'REQUIRED_FIELDS'):
    if not (User.USERNAME_FIELD == 'email' or 'email' in User.REQUIRED_FIELDS):
        raise ImproperlyConfigured(
            "EmailBackend: Your User model must have an email"
            " field with blank=False")


# 电子邮件后端
class EmailBackend(ModelBackend):
    """
    Custom auth backend that uses an email address and password

    For this to work, the User model must have an 'email' field

    使用电子邮件地址和密码的自定义身份验证后端为此，用户模型必须具
    有“电子邮件”字段
    """

    def _authenticate(self, request, email=None, password=None, *args, **kwargs):
        if email is None:
            if 'username' not in kwargs or kwargs['username'] is None:
                return None
            clean_email = normalise_email(kwargs['username'])
        else:
            clean_email = normalise_email(email)

        # Check if we're dealing with an email address
        # 检查我们是否正在处理电子邮件地址
        if '@' not in clean_email:
            return None

        # Since Django doesn't enforce emails to be unique, we look for all
        # matching users and try to authenticate them all. Note that we
        # intentionally allow multiple users with the same email address
        # (has been a requirement in larger system deployments),
        # we just enforce that they don't share the same password.
        # We make a case-insensitive match when looking for emails.
        # 由于Django不强制执行电子邮件是唯一的，因此我们会查找所有匹配的用
        # 户并尝试对所有用户进行身份验证。 请注意，我们有意允许多个用户使
        # 用相同的电子邮件地址（在大型系统部署中是必需的），我们只是强制
        # 他们不共享相同的密码。
        # 我们在查找电子邮件时进行不区分大小写的匹配。
        matching_users = User.objects.filter(email__iexact=clean_email)
        authenticated_users = [
            user for user in matching_users if (user.check_password(password) and self.user_can_authenticate(user))]
        if len(authenticated_users) == 1:
            # Happy path
            # 程序主逻辑
            return authenticated_users[0]
        elif len(authenticated_users) > 1:
            # This is the problem scenario where we have multiple users with
            # the same email address AND password. We can't safely authenticate
            # either.
            # 这是一个问题场景，我们有多个用户拥有相同的电子邮件地址和
            # 密码。我们也不能安全地进行认证。
            raise User.MultipleObjectsReturned(
                "There are multiple users with the given email address and "
                "password")
            # 有多个用户使用给定的电子邮件地址和密码
        return None

    def authenticate(self, *args, **kwargs):
        return self._authenticate(*args, **kwargs)
