from django.utils.translation import gettext_lazy as _

from oscar.core.loading import get_class, get_model

# 报表生成器
ReportGenerator = get_class('dashboard.reports.reports', 'ReportGenerator')
# 报告CSV格式化程序
ReportCSVFormatter = get_class('dashboard.reports.reports',
                               'ReportCSVFormatter')
# 报告HTML格式化程序
ReportHTMLFormatter = get_class('dashboard.reports.reports',
                                'ReportHTMLFormatter')
# 产品记录
ProductRecord = get_model('analytics', 'ProductRecord')
# 用户记录
UserRecord = get_model('analytics', 'UserRecord')


# 报告CSV格式化程序
class ProductReportCSVFormatter(ReportCSVFormatter):
    filename_template = 'conditional-offer-performance.csv'

    # 生成CSV
    def generate_csv(self, response, products):
        writer = self.get_csv_writer(response)
        header_row = [_('Product'),
                      _('Views'),
                      _('Basket additions'),
                      _('Purchases')]
        writer.writerow(header_row)

        for record in products:
            row = [record.product,
                   record.num_views,
                   record.num_basket_additions,
                   record.num_purchases]
            writer.writerow(row)


# 报告HTML格式化程序
class ProductReportHTMLFormatter(ReportHTMLFormatter):
    filename_template = 'dashboard/reports/partials/product_report.html'


# 产品报告生成器
class ProductReportGenerator(ReportGenerator):
    code = 'product_analytics'
    description = _('Product analytics')

    # 格式程序
    formatters = {
        'CSV_formatter': ProductReportCSVFormatter,
        'HTML_formatter': ProductReportHTMLFormatter}

    # 报表描述
    def report_description(self):
        return self.description

    # 生成
    def generate(self):
        records = ProductRecord._default_manager.all()
        return self.formatter.generate_response(records)

    # 可用于
    def is_available_to(self, user):
        return user.is_staff


# 用户报告CSV格式化程序
class UserReportCSVFormatter(ReportCSVFormatter):
    filename_template = 'user-analytics.csv'

    # 生成CSV
    def generate_csv(self, response, users):
        writer = self.get_csv_writer(response)
        header_row = [_('Name'),
                      _('Date registered'),
                      _('Product views'),
                      _('Basket additions'),
                      _('Orders'),
                      _('Order lines'),
                      _('Order items'),
                      _('Total spent'),
                      _('Date of last order')]
        writer.writerow(header_row)

        for record in users:
            row = [record.user.get_full_name(),
                   self.format_date(record.user.date_joined),
                   record.num_product_views,
                   record.num_basket_additions,
                   record.num_orders,
                   record.num_order_lines,
                   record.num_order_items,
                   record.total_spent,
                   self.format_datetime(record.date_last_order)]
            writer.writerow(row)


# 用户报告HTML格式化程序
class UserReportHTMLFormatter(ReportHTMLFormatter):
    filename_template = 'dashboard/reports/partials/user_report.html'


# 用户报告生成器
class UserReportGenerator(ReportGenerator):
    code = 'user_analytics'
    description = _('User analytics')

    formatters = {
        'CSV_formatter': UserReportCSVFormatter,
        'HTML_formatter': UserReportHTMLFormatter}

    def generate(self):
        users = UserRecord._default_manager.select_related().all()
        return self.formatter.generate_response(users)

    def is_available_to(self, user):
        return user.is_staff
