from datetime import datetime, time

from django.http import HttpResponse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from oscar.core import utils
from oscar.core.compat import UnicodeCSVWriter


# 报告生成器
class ReportGenerator(object):
    """
    Top-level class that needs to be subclassed to provide a
    report generator.
    需要进行子类化以提供报告生成器的顶级类。
    """
    filename_template = 'report-%s-to-%s.csv'
    content_type = 'text/csv'
    code = ''
    description = '<insert report description>'
    date_range_field_name = None

    def __init__(self, **kwargs):
        self.start_date = kwargs.get('start_date')
        self.end_date = kwargs.get('end_date')

        formatter_name = '%s_formatter' % kwargs['formatter']
        self.formatter = self.formatters[formatter_name]()

    def report_description(self):
        return _('%(report_filter)s between %(start_date)s and %(end_date)s') \
            % {'report_filter': self.description,
               'start_date': self.start_date,
               'end_date': self.end_date,
               }

    def generate(self):
        pass

    def filename(self):
        """
        Returns the filename for this report
        返回此报告的文件名
        """
        return self.formatter.filename()

    def is_available_to(self, user):
        """
        Checks whether this report is available to this user
        检查此用户是否可以使用此报告
        """
        return user.is_staff

    def filter_with_date_range(self, queryset):
        """
        Filter results based that are within a (possibly open ended) daterange
        基于（可能是开放式）数据流的过滤结果
        """
        # Nothing to do if we don't have a date field
        # 如果我们没有日期字段，那就没事可做
        if not self.date_range_field_name:
            return queryset

        # After the start date
        # 开始日期之后
        if self.start_date:
            start_datetime = timezone.make_aware(
                datetime.combine(self.start_date, time(0, 0)),
                timezone.get_default_timezone())

            filter_kwargs = {
                "%s__gt" % self.date_range_field_name: start_datetime,
            }
            queryset = queryset.filter(**filter_kwargs)

        # Before the end of the end date
        # 在结束日期结束之前
        if self.end_date:
            end_of_end_date = datetime.combine(
                self.end_date,
                time(hour=23, minute=59, second=59)
            )
            end_datetime = timezone.make_aware(end_of_end_date,
                                               timezone.get_default_timezone())
            filter_kwargs = {
                "%s__lt" % self.date_range_field_name: end_datetime,
            }
            queryset = queryset.filter(**filter_kwargs)

        return queryset


# 报告格式化程序
class ReportFormatter(object):
    def format_datetime(self, dt):
        if not dt:
            return ''
        return utils.format_datetime(dt, 'DATETIME_FORMAT')

    def format_date(self, d):
        if not d:
            return ''
        return utils.format_datetime(d, 'DATE_FORMAT')

    def filename(self):
        return self.filename_template


# 报告CSV格式化程序
class ReportCSVFormatter(ReportFormatter):

    def get_csv_writer(self, file_handle, **kwargs):
        return UnicodeCSVWriter(open_file=file_handle, **kwargs)

    def generate_response(self, objects, **kwargs):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename=%s' \
            % self.filename(**kwargs)
        self.generate_csv(response, objects)
        return response


# 报告HTML格式化程序
class ReportHTMLFormatter(ReportFormatter):

    def generate_response(self, objects, **kwargs):
        return objects
