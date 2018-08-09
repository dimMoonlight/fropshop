import json

from django.conf import settings

from oscar.core.loading import get_model

Product = get_model('catalogue', 'Product')


def get(request):
    """
    Return a list of recently viewed products
    返回最近查看的产品列表
    """
    ids = extract(request)

    # Reordering as the ID order gets messed up in the query
    # 重新排序为ID顺序在查询中搞砸了
    product_dict = Product.browsable.in_bulk(ids)
    ids.reverse()
    return [product_dict[id] for id in ids if id in product_dict]


def extract(request, response=None):
    """
    Extract the IDs of products in the history cookie
    提取历史记录cookie中的产品ID
    """
    ids = []
    cookie_name = settings.OSCAR_RECENTLY_VIEWED_COOKIE_NAME
    if cookie_name in request.COOKIES:
        try:
            ids = json.loads(request.COOKIES[cookie_name])
        except ValueError:
            # This can occur if something messes up the cookie
            # 如果某些东西搞砸了cookie，就会发生这种情况
            if response:
                response.delete_cookie(cookie_name)
        else:
            # Badly written web crawlers send garbage in double quotes
            # 写得很糟糕的网页抓取工具用双引号发送垃圾
            if not isinstance(ids, list):
                ids = []
    return ids


def add(ids, new_id):
    """
    Add a new product ID to the list of product IDs
    将新产品ID添加到产品ID列表中
    """
    max_products = settings.OSCAR_RECENTLY_VIEWED_PRODUCTS
    if new_id in ids:
        ids.remove(new_id)
    ids.append(new_id)
    if (len(ids) > max_products):
        ids = ids[len(ids) - max_products:]
    return ids


def update(product, request, response):
    """
    Updates the cookies that store the recently viewed products
    removing possible duplicates.

    更新存储最近查看的产品的cookie，删除可能的重复项。
    """
    ids = extract(request, response)
    updated_ids = add(ids, product.id)
    response.set_cookie(
        settings.OSCAR_RECENTLY_VIEWED_COOKIE_NAME,
        json.dumps(updated_ids),
        max_age=settings.OSCAR_RECENTLY_VIEWED_COOKIE_LIFETIME,
        secure=settings.OSCAR_RECENTLY_VIEWED_COOKIE_SECURE,
        httponly=True)
