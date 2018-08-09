from django.urls import reverse_lazy

from oscar.core.loading import feature_hidden
from oscar.views.decorators import permissions_required


try:
    # Django 2
    from django.urls import URLPattern
except ImportError:
    # Django 1.11
    from django.urls.resolvers import RegexURLPattern as URLPattern


class Application(object):
    """
    Base application class.

    This is subclassed by each app to provide a customisable container for an
    app's views and permissions.

    基础应用程序类。
    这是每个应用程序的子类，为应用程序的视图和权限提供可自定义的容器。
    """
    #: Application name 应用名称
    name = None

    login_url = None

    #: A name that allows the functionality within this app to be disabled
    # 一个名称，允许禁用此应用程序中的功能
    hidable_feature_name = None

    #: Maps view names to lists of permissions. We expect tuples of
    #: lists as dictionary values. A list is a set of permissions that all
    #: needto be fulfilled (AND). Only one set of permissions has to be
    #: fulfilled (OR).
    #: If there's only one set of permissions, as a shortcut, you can also
    #: just define one list.
    # 将视图名称映射到权限列表。 我们期望列表的元组作为字典值。 列表是一组
    # 需要满足的权限（AND）。 只需要满足一组权限（OR）。
    # 如果只有一组权限，作为快捷方式，您也可以只定义一个列表。
    permissions_map = {}

    #: Default permission for any view not in permissions_map
    # 不在permissions_map中的任何视图的默认权限
    default_permissions = None

    def __init__(self, app_name=None, **kwargs):
        """
        kwargs:
            app_name: optionally specify the instance namespace

        kwargs：
            app_name：可选择指定实例名称空间
        """
        self.app_name = app_name or self.name
        # Set all kwargs as object attributes
        # 将所有kwargs设置为对象属性
        for key, value in kwargs.items():
            setattr(self, key, value)

    def get_urls(self):
        """
        Return the url patterns for this app.
        返回此应用的网址格式。
        """
        return []

    def post_process_urls(self, urlpatterns):
        """
        Customise URL patterns.

        This method allows decorators to be wrapped around an apps URL
        patterns.

        By default, this only allows custom decorators to be specified, but you
        could override this method to do anything you want.

        Args:
            urlpatterns (list): A list of URL patterns

        自定义URL模式。
        此方法允许装饰器包裹应用程序URL模式。
        默认情况下，这只允许指定自定义装饰器，但您可以覆盖此方法以执行任何操作。
        Args:
            urlpatterns（list）：URL模式列表
        """
        # Test if this the URLs in the Application instance should be
        # available.  If the feature is hidden then we don't include the URLs.
        # 测试应用程序实例中的URL是否可用。 如果隐藏该功能，则我们不会包含这些网址。
        if feature_hidden(self.hidable_feature_name):
            return []

        for pattern in urlpatterns:
            if hasattr(pattern, 'url_patterns'):
                self.post_process_urls(pattern.url_patterns)

            if isinstance(pattern, URLPattern):
                # Apply the custom view decorator (if any) set for this class if this
                # is a URL Pattern.
                # 如果这是一个URL模式，则应用为此类设置的自定义视图装饰器（如果有）。
                decorator = self.get_url_decorator(pattern)
                if decorator:
                    pattern.callback = decorator(pattern.callback)

        return urlpatterns

    def get_permissions(self, url):
        """
        Return a list of permissions for a given URL name

        Args:
            url (str): A URL name (eg ``basket.basket``)

        Returns:
            list: A list of permission strings.

        返回给定URL名称的权限列表
        ARGS：
            url（str）：一个URL名称（例如``basket.basket``）
        Returns：
            list：权限字符串列表。
        """
        # url namespaced? URL名称间隔？
        if url is not None and ':' in url:
            view_name = url.split(':')[1]
        else:
            view_name = url
        return self.permissions_map.get(view_name, self.default_permissions)

    def get_url_decorator(self, pattern):
        """
        Return the appropriate decorator for the view function with the passed
        URL name. Mainly used for access-protecting views.

        It's possible to specify:

        - no permissions necessary: use None
        - a set of permissions: use a list
        - two set of permissions (`or`): use a two-tuple of lists

        See permissions_required decorator for details

        使用传递的URL名称返回视图函数的相应装饰器。 主要用于访问保护视图。
        可以指定：
        - 无需权限：使用None
        - 一组权限：使用列表
        - 两组权限（`或`）：使用两元组列表
        有关详细信息，请参见permission_required装饰器
        """
        permissions = self.get_permissions(pattern.name)
        if permissions:
            return permissions_required(permissions, login_url=self.login_url)

    @property
    def urls(self):
        # We set the application and instance namespace here
        # 我们在这里设置应用程序和实例名称空间
        return self.get_urls(), self.name, self.app_name


class DashboardApplication(Application):
    login_url = reverse_lazy('dashboard:login')
