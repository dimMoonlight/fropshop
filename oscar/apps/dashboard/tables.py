from django.utils.translation import ungettext_lazy
from django_tables2 import Table


class DashboardTable(Table):
    caption = ungettext_lazy('%d Row', '%d Rows')

    def get_caption_display(self):
        # Allow overriding the caption with an arbitrary string that we cannot
        # interpolate the number of rows in
        # 允许用一个不能插入行数的任意字符串重写标题。
        try:
            return self.caption % self.paginator.count
        except TypeError:
            pass
        return self.caption

    class Meta:
        template = 'dashboard/table.html'
        attrs = {'class': 'table table-striped table-bordered'}
