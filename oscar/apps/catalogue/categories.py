from oscar.core.loading import get_model

Category = get_model('catalogue', 'category')


# 从序列创建
def create_from_sequence(bits):
    """
    Create categories from an iterable
    从可迭代创建类别
    """
    if len(bits) == 1:
        # Get or create root node
        # 获取或创建根节点
        name = bits[0]
        try:
            # Category names should be unique at the depth=1
            # 类别名称在 depth=1 时应该是唯一的
            root = Category.objects.get(depth=1, name=name)
        except Category.DoesNotExist:
            root = Category.add_root(name=name)
        except Category.MultipleObjectsReturned:
            # 名称不止一个类别
            raise ValueError((
                "There are more than one categories with name "
                "%s at depth=1") % name)
        return [root]
    else:
        parents = create_from_sequence(bits[:-1])
        parent, name = parents[-1], bits[-1]
        try:
            child = parent.get_children().get(name=name)
        except Category.DoesNotExist:
            child = parent.add_child(name=name)
        except Category.MultipleObjectsReturned:
            # 名称不止一个类别
            raise ValueError((
                "There are more than one categories with name "
                "%s which are children of %s") % (name, parent))
        parents.append(child)
        return parents


def create_from_breadcrumbs(breadcrumb_str, separator='>'):
    """
    Create categories from a breadcrumb string
    """
    category_names = [x.strip() for x in breadcrumb_str.split(separator)]
    categories = create_from_sequence(category_names)
    return categories[-1]
