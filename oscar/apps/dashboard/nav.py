import logging
import re

from django.core.exceptions import ImproperlyConfigured
from django.urls import NoReverseMatch, resolve, reverse

from oscar.core.loading import AppNotFoundError, get_class
from oscar.views.decorators import check_permissions

logger = logging.getLogger('oscar.dashboard')


class Node(object):
    """
    A node in the dashboard navigation menu
    仪表板导航菜单中的节点
    """

    def __init__(self, label, url_name=None, url_args=None, url_kwargs=None,
                 access_fn=None, icon=None):
        self.label = label
        self.icon = icon
        self.url_name = url_name
        self.url_args = url_args
        self.url_kwargs = url_kwargs
        self.access_fn = access_fn
        self.children = []

    @property
    def is_heading(self):
        return self.url_name is None

    @property
    def url(self):
        return reverse(self.url_name, args=self.url_args,
                       kwargs=self.url_kwargs)

    def add_child(self, node):
        self.children.append(node)

    def is_visible(self, user):
        return self.access_fn is None or self.access_fn(
            user, self.url_name, self.url_args, self.url_kwargs)

    def filter(self, user):
        if not self.is_visible(user):
            return None
        node = Node(
            label=self.label, url_name=self.url_name, url_args=self.url_args,
            url_kwargs=self.url_kwargs, access_fn=self.access_fn,
            icon=self.icon
        )
        for child in self.children:
            if child.is_visible(user):
                node.add_child(child)
        return node

    def has_children(self):
        return len(self.children) > 0


def default_access_fn(user, url_name, url_args=None, url_kwargs=None):
    """
    Given a url_name and a user, this function tries to assess whether the
    user has the right to access the URL.
    The application instance of the view is fetched via dynamic imports,
    and those assumptions will only hold true if the standard Oscar layout
    is followed.
    Once the permissions for the view are known, the access logic used
    by the dashboard decorator is evaluated

    This function might seem costly, but a simple comparison with DTT
    did not show any change in response time

    给定url_name和用户，此函数尝试评估用户是否有权访问URL。

    视图的应用程序实例是通过动态导入获取的，只有遵循标准的Oscar布局，这些假设才会成立。

    一旦知道了视图的权限，就会评估仪表板装饰器使用的访问逻辑

    此功能可能看起来很昂贵，但与DTT的简单比较并未显示响应时间的任何变化
    """
    exception = ImproperlyConfigured(
        "Please follow Oscar's default dashboard app layout or set a "
        "custom access_fn")
    # 请遵循Oscar的默认仪表板应用布局或设置自定义access_fn
    if url_name is None:  # it's a heading  这是一个标题
        return True

    # get view module string. 获取视图模块字符串。
    try:
        url = reverse(url_name, args=url_args, kwargs=url_kwargs)
    except NoReverseMatch:
        # In Oscar 1.5 this exception was silently ignored which made debugging
        # very difficult. Now it is being logged and in future the exception will
        # be propagated.
        # 在Oscar 1.5中，这个异常被忽略了，这使调试变得非常困难。 现在它正在被记录，将来会传播异常。
        logger.exception('Invalid URL name {}'.format(url_name))
        return False

    view_module = resolve(url).func.__module__

    # We can't assume that the view has the same parent module as the app,
    # as either the app or view can be customised. So we turn the module
    # string (e.g. 'oscar.apps.dashboard.catalogue.views') into an app
    # label that can be loaded by get_class (e.g.
    # 'dashboard.catalogue.app), which then essentially checks
    # INSTALLED_APPS for the right module to load
    # 我们不能假设视图与应用程序具有相同的父模块，因为可以自定义应用程序或视图。
    #  因此，我们将模块字符串（例如'oscar.apps.dashboard.catalogue.views'）转换为可
    # 由get_class（eg'dashboard.catalogue.app）加载的应用程序标签，然后基本上
    # 将INSTALLED_APPS检查为正确的模块 加载
    match = re.search('(dashboard[\w\.]*)\.views$', view_module)
    if not match:
        raise exception
    app_label_str = match.groups()[0] + '.app'

    try:
        app_instance = get_class(app_label_str, 'application')
    except AppNotFoundError:
        raise exception

    # handle name-spaced view names 处理名称间隔的视图名称
    if ':' in url_name:
        view_name = url_name.split(':')[1]
    else:
        view_name = url_name
    permissions = app_instance.get_permissions(view_name)
    return check_permissions(user, permissions)
