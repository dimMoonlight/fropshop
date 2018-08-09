from django.urls import reverse
from django.views.generic import RedirectView, TemplateView


class HomeView(TemplateView):
    """
    This is the home page and will typically live at /
    这是主页，通常会居住在/
    """
    template_name = 'promotions/home.html'


class RecordClickView(RedirectView):
    """
    Simple RedirectView that helps recording clicks made on promotions
    简单的RedirectView，可帮助记录促销中的点击次数
    """
    permanent = False
    model = None

    def get_redirect_url(self, **kwargs):
        try:
            prom = self.model.objects.get(pk=kwargs['pk'])
        except self.model.DoesNotExist:
            return reverse('promotions:home')

        if prom.promotion.has_link:
            prom.record_click()
            return prom.link_url
        return reverse('promotions:home')
