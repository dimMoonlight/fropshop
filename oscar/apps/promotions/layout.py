def split_by_position(linked_promotions, context):
    """
    Split the list of promotions into separate lists, grouping
    by position, and write these lists to the passed context.
    将促销列表拆分为单独的列表，按位置分组，并将这些列表写入传递的上下文。
    """
    for linked_promotion in linked_promotions:
        promotion = linked_promotion.content_object
        if not promotion:
            continue
        key = 'promotions_%s' % linked_promotion.position.lower()
        if key not in context:
            context[key] = []
        context[key].append(promotion)
