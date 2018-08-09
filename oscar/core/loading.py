import sys
import traceback
import warnings
from importlib import import_module

from django.apps import apps
from django.apps.config import MODELS_MODULE_NAME
from django.conf import settings
from django.core.exceptions import AppRegistryNotReady
from django.utils.lru_cache import lru_cache
from django.utils.module_loading import import_string

from oscar.core.exceptions import (
    AppNotFoundError, ClassNotFoundError, ModuleNotFoundError)

# To preserve backwards compatibility of loading classes which moved
# from one Oscar module to another, we look into the dictionary below
# for the moved items during loading.
# 为了保持从一个Oscar模块移动到另一个Oscar模块的加载类的向后兼容性，我们
# 在加载期间查看下面的字典以了解移动的项目。
MOVED_ITEMS = {
    'oscar.apps.basket.forms': (
        'oscar.apps.basket.formsets', ('BaseBasketLineFormSet', 'BasketLineFormSet',
                                       'BaseSavedLineFormSet', 'SavedLineFormSet')
    ),
    'oscar.apps.dashboard.catalogue.forms': (
        'oscar.apps.dashboard.catalogue.formsets', ('BaseStockRecordFormSet',
                                                    'StockRecordFormSet',
                                                    'BaseProductCategoryFormSet',
                                                    'ProductCategoryFormSet',
                                                    'BaseProductImageFormSet',
                                                    'ProductImageFormSet',
                                                    'BaseProductRecommendationFormSet',
                                                    'ProductRecommendationFormSet',
                                                    'ProductAttributesFormSet')
    ),
    'oscar.apps.dashboard.promotions.forms': (
        'oscar.apps.dashboard.promotions.formsets', ('OrderedProductFormSet',)
    ),
    'oscar.apps.wishlists.forms': (
        'oscar.apps.wishlists.formsets', ('LineFormset',)
    )
}


def get_class(module_label, classname, module_prefix='oscar.apps'):
    """
    Dynamically import a single class from the given module.

    This is a simple wrapper around `get_classes` for the case of loading a
    single class.

    Args:
        module_label (str): Module label comprising the app label and the
            module name, separated by a dot.  For example, 'catalogue.forms'.
        classname (str): Name of the class to be imported.

    Returns:
        The requested class object or `None` if it can't be found

    从给定模块动态导入单个类。
    对于加载单个类的情况，这是一个简单的`get_classes`包装器。
    Args:
        module_label（str）：模块标签，包含应用标签和模块名称，用点分隔。
         例如，'catalogue.forms'
        classname（str）：要导入的类的名称。
    Returns:
        请求的类对象，如果找不到，则为“None”
    """
    return get_classes(module_label, [classname], module_prefix)[0]


@lru_cache(maxsize=100)
def get_class_loader():
    return import_string(settings.OSCAR_DYNAMIC_CLASS_LOADER)


def get_classes(module_label, classnames, module_prefix='oscar.apps'):
    class_loader = get_class_loader()
    return class_loader(module_label, classnames, module_prefix)


def default_class_loader(module_label, classnames, module_prefix):
    """
    Dynamically import a list of classes from the given module.

    This works by looping over ``INSTALLED_APPS`` and looking for a match
    against the passed module label.  If the requested class can't be found in
    the matching module, then we attempt to import it from the corresponding
    core app.

    This is very similar to ``django.db.models.get_model`` function for
    dynamically loading models.  This function is more general though as it can
    load any class from the matching app, not just a model.

    Args:
        module_label (str): Module label comprising the app label and the
            module name, separated by a dot.  For example, 'catalogue.forms'.
        classname (str): Name of the class to be imported.

    Returns:
        The requested class object or ``None`` if it can't be found

    Examples:

        Load a single class:

        >>> get_class('dashboard.catalogue.forms', 'ProductForm')
        oscar.apps.dashboard.catalogue.forms.ProductForm

        Load a list of classes:

        >>> get_classes('dashboard.catalogue.forms',
        ...             ['ProductForm', 'StockRecordForm'])
        [oscar.apps.dashboard.catalogue.forms.ProductForm,
         oscar.apps.dashboard.catalogue.forms.StockRecordForm]

    Raises:

        AppNotFoundError: If no app is found in ``INSTALLED_APPS`` that matches
            the passed module label.

        ImportError: If the attempted import of a class raises an
            ``ImportError``, it is re-raised

    动态导入给定模块的类列表。
    这是通过循环``INSTALLED_APPS``并寻找与传递的模块标签的匹配来实现的。 如果在
    匹配模块中找不到请求的类，那么我们尝试从相应的核心应用程序导入它。
    这与用于动态加载模型的``django.db.models.get_model``函数非常相似。 这个函数
    更通用，因为它可以从匹配的应用程序加载任何类，而不仅仅是模型。
    Args:
        module_label（str）：模块标签，包含应用标签和模块名称，用点分隔。 例如，'catalogue.forms'。
        classname（str）：要导入的类的名称。
    Returns:
        请求的类对象，如果找不到，则为“无”

    例子：
        加载一个类：
        >>> get_class('dashboard.catalogue.forms', 'ProductForm')
        oscar.apps.dashboard.catalogue.forms.ProductForm
        加载类列表：
        >>> get_classes('dashboard.catalogue.forms',
        ...             ['ProductForm', 'StockRecordForm'])
        [oscar.apps.dashboard.catalogue.forms.ProductForm,
        oscar.apps.dashboard.catalogue.forms.StockRecordForm]

     Raises:
         AppNotFoundError：如果在``INSTALLED_APPS``中找不到与传递的模块标签匹配的应用程序。
         ImportError：如果尝试导入类引发了``ImportError``，则会重新引发它
    """

    if '.' not in module_label:
        # Importing from top-level modules is not supported, e.g.
        # get_class('shipping', 'Scale'). That should be easy to fix,
        # but @maikhoepfel had a stab and could not get it working reliably.
        # Overridable classes in a __init__.py might not be a good idea anyway.
        # 不支持从顶级模块导入，例如 get_class（'shipping'，'Scale'）。 这应该
        # 很容易修复，但@maikhoepfel有一个刺，无法让它可靠地工作。
        # 无论如何，__ init__.py中的可覆盖类可能不是一个好主意。
        raise ValueError(
            "Importing from top-level modules is not supported")

    # import from Oscar package (should succeed in most cases)
    # e.g. 'oscar.apps.dashboard.catalogue.forms'
    # 从奥斯卡包装进口（在大多数情况下应该成功），
    # 例如'oscar.apps.dashboard.catalogue.forms'
    oscar_module_label = "%s.%s" % (module_prefix, module_label)
    oscar_module = _import_module(oscar_module_label, classnames)

    # returns e.g. 'oscar.apps.dashboard.catalogue',
    # 'yourproject.apps.dashboard.catalogue' or 'dashboard.catalogue',
    # depending on what is set in INSTALLED_APPS

    # 返回 例如 'oscar.apps.dashboard.catalogue'，
    # 'yourproject.apps.dashboard.catalogue'或'dashboard.catalogue'，
    # 具体取决于INSTALLED_APPS中的设置
    installed_apps_entry, app_name = _find_installed_apps_entry(module_label)
    if installed_apps_entry.startswith('%s.' % module_prefix):
        # The entry is obviously an Oscar one, we don't import again
        # 条目显然是Oscar的，我们不会再次导入。
        local_module = None
    else:
        # Attempt to import the classes from the local module
        # e.g. 'yourproject.dashboard.catalogue.forms'
        # 尝试从本地模块导入类
        # 例如'yourproject.dashboard.catalogue.forms'
        sub_module = module_label.replace(app_name, '', 1)
        local_module_label = installed_apps_entry + sub_module
        local_module = _import_module(local_module_label, classnames)

    # Checking whether module label has corresponding move module in the MOVED_ITEMS dictionary.
    # If it does, checking if any of the loading classes moved to another module.
    # Finally, it they did, importing move module and showing deprecation warning as well.
    # 检查模块标签是否在MOVED_ITEMS字典中有相应的移动模块。
    # 如果是，请检查是否有任何加载类移动到另一个模块。
    # 最后，他们做了，导入移动模块并显示弃用警告。
    oscar_move_item = MOVED_ITEMS.get(oscar_module_label, None)
    if oscar_move_item:
        oscar_move_module_label = oscar_move_item[0]
        oscar_move_classnames = oscar_move_item[1]
        oscar_moved_classnames = list(set(oscar_move_classnames).intersection(classnames))
        if oscar_moved_classnames:
            warnings.warn(
                'Classes %s has recently moved to the new destination module - %s, '
                'please update your imports.' % (', '.join(oscar_moved_classnames),
                                                 oscar_move_module_label),
                DeprecationWarning, stacklevel=2)
            oscar_move_module = _import_module(oscar_move_module_label, classnames)
        else:
            oscar_move_module = None
    else:
        oscar_move_module = None

    if oscar_module is oscar_move_module is local_module is None:
        # This intentionally doesn't raise an ImportError, because ImportError
        # can get masked in complex circular import scenarios.
        # 这故意不会引发ImportError，因为在复杂的循环导入方案中可能会掩盖ImportError。
        raise ModuleNotFoundError(
            "The module with label '%s' could not be imported. This either"
            "means that it indeed does not exist, or you might have a problem"
            " with a circular import." % module_label
        )

    # return imported classes, giving preference to ones from the local package
    # 返回导入的类，优先使用本地包中的类
    return _pluck_classes([local_module, oscar_module, oscar_move_module], classnames)


def _import_module(module_label, classnames):
    """
    Imports the module with the given name.
    Returns None if the module doesn't exist, but propagates any import errors.

    使用给定名称导入模块。
    如果模块不存在，则返回None，但传播任何导入错误。
    """
    try:
        return __import__(module_label, fromlist=classnames)
    except ImportError:
        # There are 2 reasons why there could be an ImportError:
        #
        #  1. Module does not exist. In that case, we ignore the import and
        #     return None
        #  2. Module exists but another ImportError occurred when trying to
        #     import the module. In that case, it is important to propagate the
        #     error.
        #
        # ImportError does not provide easy way to distinguish those two cases.
        # Fortunately, the traceback of the ImportError starts at __import__
        # statement. If the traceback has more than one frame, it means that
        # application was found and ImportError originates within the local app

        # 可能存在ImportError的原因有两个：
        #
        # 1.模块不存在。 在这种情况下，我们忽略导入并返回None
        # 2.模块存在但尝试导入模块时发生了另一个ImportError。 在这种情况下，传播错误很重要。
        #
        # ImportError不提供区分这两种情况的简便方法。
        # 幸运的是，ImportError的回溯始于__import__语句。 如果回溯具有多个帧，则
        # 表示找到了应用程序，并且ImportError来自本地应用程序
        __, __, exc_traceback = sys.exc_info()
        frames = traceback.extract_tb(exc_traceback)
        if len(frames) > 1:
            raise


def _pluck_classes(modules, classnames):
    """
    Gets a list of class names and a list of modules to pick from.
    For each class name, will return the class from the first module that has a
    matching class.

    获取类名列表和要从中选择的模块列表。
    对于每个类名，将从具有匹配类的第一个模块返回该类。
    """
    klasses = []
    for classname in classnames:
        klass = None
        for module in modules:
            if hasattr(module, classname):
                klass = getattr(module, classname)
                break
        if not klass:
            packages = [m.__name__ for m in modules if m is not None]
            raise ClassNotFoundError("No class '%s' found in %s" % (
                classname, ", ".join(packages)))
        klasses.append(klass)
    return klasses


def _get_installed_apps_entry(app_name):
    """
    Given an app name (e.g. 'catalogue'), walk through INSTALLED_APPS
    and return the first match, or None.
    This does depend on the order of INSTALLED_APPS and will break if
    e.g. 'dashboard.catalogue' comes before 'catalogue' in INSTALLED_APPS.

    给定应用程序名称（例如“目录”），遍历INSTALLED_APPS并返回第一个匹配，
    或者返回None。
    这取决于INSTALLED_APPS的顺序，如果例如，则会中断 'dashboard.catalogue'位
    于INSTALLED_APPS中的'catalog'之前。
    """
    for installed_app in settings.INSTALLED_APPS:
        # match root-level apps ('catalogue') or apps with same name at end
        # ('shop.catalogue'), but don't match 'fancy_catalogue'
        # 匹配根级应用程序（'目录'）或结尾具有相同名称的应用程序（'shop.catalogue'），
        # 但不匹配'fancy_catalogue'
        if installed_app == app_name or installed_app.endswith('.' + app_name):
            return installed_app
    return None


def _find_installed_apps_entry(module_label):
    """
    Given a module label, finds the best matching INSTALLED_APPS entry.

    This is made trickier by the fact that we don't know what part of the
    module_label is part of the INSTALLED_APPS entry. So we try all possible
    combinations, trying the longer versions first. E.g. for
    'dashboard.catalogue.forms', 'dashboard.catalogue' is attempted before
    'dashboard'

    给定模块标签，找到最匹配的INSTALLED_APPS条目。
    由于我们不知道module_label的哪个部分是INSTALLED_APPS条目的一部分，所以这
    变得更加棘手。 所以我们尝试所有可能的组合，首先尝试更长的版本。 例如。 对
    于“dashboard.catalogue.forms”，在“仪表板”之前尝试“dashboard.catalogue”
    """
    modules = module_label.split('.')
    # if module_label is 'dashboard.catalogue.forms.widgets', combinations
    # will be ['dashboard.catalogue.forms', 'dashboard.catalogue', 'dashboard']
    # 如果module_label是'dashboard.catalogue.forms.widgets'，则组合将
    # 是['dashboard.catalogue.forms'，'dashboard.catalogue'，'dashboard']
    combinations = [
        '.'.join(modules[:-count]) for count in range(1, len(modules))]
    for app_name in combinations:
        entry = _get_installed_apps_entry(app_name)
        if entry:
            return entry, app_name
    raise AppNotFoundError(
        "Couldn't find an app to import %s from" % module_label)


def get_profile_class():
    """
    Return the profile model class
    返回配置文件模型类
    """
    # The AUTH_PROFILE_MODULE setting was deprecated in Django 1.5, but it
    # makes sense for Oscar to continue to use it. Projects built on Django
    # 1.4 are likely to have used a profile class and it's very difficult to
    # upgrade to a single user model. Hence, we should continue to support
    # having a separate profile class even if Django doesn't.
    # 在Django 1.5中不推荐使用AUTH_PROFILE_MODULE设置，但是Oscar继续使用它是有意
    # 义的。 在Django 1.4上构建的项目可能使用了配置文件类，并且很难升级到单个用户
    # 模型。 因此，即使Django没有，我们仍应继续支持单独的配置文件类。
    setting = getattr(settings, 'AUTH_PROFILE_MODULE', None)
    if setting is None:
        return None
    app_label, model_name = settings.AUTH_PROFILE_MODULE.split('.')
    return get_model(app_label, model_name)


def feature_hidden(feature_name):
    """
    Test if a certain Oscar feature is disabled.
    测试是否禁用某个Oscar功能。
    """
    return (feature_name is not None and
            feature_name in settings.OSCAR_HIDDEN_FEATURES)


def get_model(app_label, model_name):
    """
    Fetches a Django model using the app registry.

    This doesn't require that an app with the given app label exists,
    which makes it safe to call when the registry is being populated.
    All other methods to access models might raise an exception about the
    registry not being ready yet.
    Raises LookupError if model isn't found.

    使用app注册表获取Django模型。
    这不要求具有给定app标签的应用程序存在，这使得在填充注册表时可以安全地调用。
    访问模型的所有其他方法可能会引发有关注册表尚未准备就绪的异常。
    如果找不到模型，则引发LookupError。
    """
    try:
        return apps.get_model(app_label, model_name)
    except AppRegistryNotReady:
        if apps.apps_ready and not apps.models_ready:
            # If this function is called while `apps.populate()` is
            # loading models, ensure that the module that defines the
            # target model has been imported and try looking the model up
            # in the app registry. This effectively emulates
            # `from path.to.app.models import Model` where we use
            # `Model = get_model('app', 'Model')` instead.
            # 如果在'apps.populate（）`正在加载模型时调用此函数，请确保已导入定义
            # 目标模型的模块并尝试在app注册表中查找模型。 这有效地模仿了path.to.app.models
            # 导入Model`，我们使用Model = get_model（'app'，'Model'）来代替。
            app_config = apps.get_app_config(app_label)
            # `app_config.import_models()` cannot be used here because it
            # would interfere with `apps.populate()`.
            # `app_config.import_models（）`不能在这里使用，因为它会干扰`apps.populate（）`。
            import_module('%s.%s' % (app_config.name, MODELS_MODULE_NAME))
            # In order to account for case-insensitivity of model_name,
            # look up the model through a private API of the app registry.
            # 为了说明model_name的大小写不敏感，请通过app注册表的私有API查找模型。
            return apps.get_registered_model(app_label, model_name)
        else:
            # This must be a different case (e.g. the model really doesn't
            # exist). We just re-raise the exception.
            # 这必须是不同的情况（例如模型确实不存在）。 我们只是重新提出异常。
            raise


def is_model_registered(app_label, model_name):
    """
    Checks whether a given model is registered. This is used to only
    register Oscar models if they aren't overridden by a forked app.
    检查给定模型是否已注册。 如果它们没有被分叉应用程序覆盖，则仅用于注册Oscar模型。
    """
    try:
        apps.get_registered_model(app_label, model_name)
    except LookupError:
        return False
    else:
        return True
