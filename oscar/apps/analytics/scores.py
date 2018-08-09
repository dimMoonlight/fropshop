from django.db.models import F

from oscar.core.loading import get_model

ProductRecord = get_model('analytics', 'ProductRecord')
Product = get_model('catalogue', 'Product')


#  计算器
class Calculator(object):

    # Map of field name to weight
    # 字段名称到权重的映射
    weights = {
        'num_views': 1,
        'num_basket_additions': 3,
        'num_purchases': 5
    }

    def __init__(self, logger):
        self.logger = logger

    def run(self):
        self.calculate_scores()

    def calculate_scores(self):
        self.logger.info("Calculating product scores")
        total_weight = float(sum(self.weights.values()))
        weighted_fields = [
            self.weights[name] * F(name) for name in self.weights.keys()]
        ProductRecord.objects.update(
            score=sum(weighted_fields) / total_weight)
