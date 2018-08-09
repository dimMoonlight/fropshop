from django.conf import settings
from django.contrib import messages
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views import generic
from django_tables2 import SingleTableMixin, SingleTableView

from oscar.core.loading import get_classes, get_model
from oscar.views.generic import ObjectLookupView

(ProductForm,
 ProductClassSelectForm,
 ProductSearchForm,
 ProductClassForm,
 CategoryForm,
 StockAlertSearchForm,
 AttributeOptionGroupForm) \
    = get_classes('dashboard.catalogue.forms',
                  ('ProductForm',
                   'ProductClassSelectForm',
                   'ProductSearchForm',
                   'ProductClassForm',
                   'CategoryForm',
                   'StockAlertSearchForm',
                   'AttributeOptionGroupForm'))
(StockRecordFormSet,
 ProductCategoryFormSet,
 ProductImageFormSet,
 ProductRecommendationFormSet,
 ProductAttributesFormSet,
 AttributeOptionFormSet) \
    = get_classes('dashboard.catalogue.formsets',
                  ('StockRecordFormSet',
                   'ProductCategoryFormSet',
                   'ProductImageFormSet',
                   'ProductRecommendationFormSet',
                   'ProductAttributesFormSet',
                   'AttributeOptionFormSet'))
ProductTable, CategoryTable, AttributeOptionGroupTable \
    = get_classes('dashboard.catalogue.tables',
                  ('ProductTable', 'CategoryTable',
                   'AttributeOptionGroupTable'))
(PopUpWindowCreateMixin,
 PopUpWindowUpdateMixin,
 PopUpWindowDeleteMixin) \
    = get_classes('dashboard.views',
                  ('PopUpWindowCreateMixin',
                   'PopUpWindowUpdateMixin',
                   'PopUpWindowDeleteMixin'))
Product = get_model('catalogue', 'Product')
Category = get_model('catalogue', 'Category')
ProductImage = get_model('catalogue', 'ProductImage')
ProductCategory = get_model('catalogue', 'ProductCategory')
ProductClass = get_model('catalogue', 'ProductClass')
StockRecord = get_model('partner', 'StockRecord')
StockAlert = get_model('partner', 'StockAlert')
Partner = get_model('partner', 'Partner')
AttributeOptionGroup = get_model('catalogue', 'AttributeOptionGroup')


# 过滤产品
def filter_products(queryset, user):
    """
    Restrict the queryset to products the given user has access to.
    A staff user is allowed to access all Products.
    A non-staff user is only allowed access to a product if they are in at
    least one stock record's partner user list.
    将查询集限制为给定用户有权访问的产品。
    允许员工用户访问所有产品。
    如果非员工用户位于至少一个库存记录的合作伙伴用户列表中，则只允许其访问产品。
    """
    if user.is_staff:
        return queryset

    return queryset.filter(stockrecords__partner__users__pk=user.pk).distinct()


# 产品列表视图
class ProductListView(SingleTableView):

    """
    Dashboard view of the product list.
    Supports the permission-based dashboard.
    产品列表的仪表板视图。
    支持基于许可的仪表板。
    """

    template_name = 'dashboard/catalogue/product_list.html'
    form_class = ProductSearchForm
    productclass_form_class = ProductClassSelectForm
    table_class = ProductTable
    context_table_name = 'products'

    # 获取上下文数据
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['form'] = self.form
        ctx['productclass_form'] = self.productclass_form_class()
        return ctx

    # 获取描述
    def get_description(self, form):
        if form.is_valid() and any(form.cleaned_data.values()):
            return _('Product search results')
        return _('Products')

    # 获得表
    def get_table(self, **kwargs):
        if 'recently_edited' in self.request.GET:
            kwargs.update(dict(orderable=False))

        table = super().get_table(**kwargs)
        table.caption = self.get_description(self.form)
        return table

    # 获取表分页
    def get_table_pagination(self, table):
        return dict(per_page=20)

    # 过滤查询集
    def filter_queryset(self, queryset):
        """
        Apply any filters to restrict the products that appear on the list
        应用任何筛选器来限制列表上出现的产品
        """
        return filter_products(queryset, self.request.user)

    # 获取查询集
    def get_queryset(self):
        """
        Build the queryset for this list
        构建此列表的查询集
        """
        queryset = Product.browsable.base_queryset()
        queryset = self.filter_queryset(queryset)
        queryset = self.apply_search(queryset)
        return queryset

    # 申请搜索
    def apply_search(self, queryset):
        """
        Filter the queryset and set the description according to the search
        parameters given
        过滤查询集并根据给定的搜索参数设置描述
        """
        self.form = self.form_class(self.request.GET)

        if not self.form.is_valid():
            return queryset

        data = self.form.cleaned_data

        if data.get('upc'):
            # Filter the queryset by upc
            # If there's an exact match, return it, otherwise return results
            # that contain the UPC
            # 通过upc过滤查询集如果存在完全匹配，则返回它，否则返回包含UPC的结果
            matches_upc = Product.objects.filter(upc=data['upc'])
            qs_match = queryset.filter(
                Q(id__in=matches_upc.values('id')) |
                Q(id__in=matches_upc.values('parent_id')))

            if qs_match.exists():
                queryset = qs_match
            else:
                matches_upc = Product.objects.filter(upc__icontains=data['upc'])
                queryset = queryset.filter(
                    Q(id__in=matches_upc.values('id')) | Q(id__in=matches_upc.values('parent_id')))

        if data.get('title'):
            queryset = queryset.filter(title__icontains=data['title'])

        return queryset


# 产品创建重定向视图
class ProductCreateRedirectView(generic.RedirectView):
    permanent = False
    productclass_form_class = ProductClassSelectForm

    def get_product_create_url(self, product_class):
        """ Allow site to provide custom URL  允许站点提供自定义URL"""
        return reverse('dashboard:catalogue-product-create',
                       kwargs={'product_class_slug': product_class.slug})

    def get_invalid_product_class_url(self):
        messages.error(self.request, _("Please choose a product type"))
        return reverse('dashboard:catalogue-product-list')

    def get_redirect_url(self, **kwargs):
        form = self.productclass_form_class(self.request.GET)
        if form.is_valid():
            product_class = form.cleaned_data['product_class']
            return self.get_product_create_url(product_class)

        else:
            return self.get_invalid_product_class_url()


# 产品创建更新视图
class ProductCreateUpdateView(generic.UpdateView):
    """
    Dashboard view that is can both create and update products of all kinds.
    It can be used in three different ways, each of them with a unique URL
    pattern:
    - When creating a new standalone product, this view is called with the
      desired product class
    - When editing an existing product, this view is called with the product's
      primary key. If the product is a child product, the template considerably
      reduces the available form fields.
    - When creating a new child product, this view is called with the parent's
      primary key.

    Supports the permission-based dashboard.


    仪表板视图可以创建和更新各种产品。
    它可以以三种不同的方式使用，每种方式都有一个唯一的URL模式：
    - 创建新的独立产品时，将使用所需的产品类调用此视图
    - 编辑现有产品时，将使用产品的主键调用此视图。 如果产品是子产品，则模板会
      显着减少可用的表单字段。
    - 创建新的子产品时，将使用父级的主键调用此视图。

    支持基于许可的仪表板。
    """

    template_name = 'dashboard/catalogue/product_update.html'
    model = Product
    context_object_name = 'product'

    form_class = ProductForm
    category_formset = ProductCategoryFormSet
    image_formset = ProductImageFormSet
    recommendations_formset = ProductRecommendationFormSet
    stockrecord_formset = StockRecordFormSet

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.formsets = {'category_formset': self.category_formset,
                         'image_formset': self.image_formset,
                         'recommended_formset': self.recommendations_formset,
                         'stockrecord_formset': self.stockrecord_formset}

    # 调度
    def dispatch(self, request, *args, **kwargs):
        resp = super().dispatch(
            request, *args, **kwargs)
        return self.check_objects_or_redirect() or resp

    # 检查对象或重定向
    def check_objects_or_redirect(self):
        """
        Allows checking the objects fetched by get_object and redirect
        if they don't satisfy our needs.
        Is used to redirect when create a new variant and the specified
        parent product can't actually be turned into a parent product.
        允许检查get_object提取的对象，如果它们不满足我们的需要，则重定向。
        用于在创建新变体时重定向，并且指定的父产品实际上无法转换为父产品。
        """
        if self.creating and self.parent is not None:
            is_valid, reason = self.parent.can_be_parent(give_reason=True)
            if not is_valid:
                messages.error(self.request, reason)
                return redirect('dashboard:catalogue-product-list')

    # 获取查询集
    def get_queryset(self):
        """
        Filter products that the user doesn't have permission to update
        过滤用户无权更新的产品
        """
        return filter_products(Product.objects.all(), self.request.user)

    # 获取对象
    def get_object(self, queryset=None):
        """
        This parts allows generic.UpdateView to handle creating products as
        well. The only distinction between an UpdateView and a CreateView
        is that self.object is None. We emulate this behavior.

        This method is also responsible for setting self.product_class and
        self.parent.

        这部分允许generic.UpdateView处理创建产品。 UpdateView和CreateView之间的
        唯一区别是self.object是None。 我们模仿这种行为。

        此方法还负责设置self.product_class和self.parent。
        """
        self.creating = 'pk' not in self.kwargs
        if self.creating:
            # Specifying a parent product is only done when creating a child
            # product.
            # 仅在创建子产品时才会指定父产品。
            parent_pk = self.kwargs.get('parent_pk')
            if parent_pk is None:
                self.parent = None
                # A product class needs to be specified when creating a
                # standalone product.
                # 创建独立产品时需要指定产品类。
                product_class_slug = self.kwargs.get('product_class_slug')
                self.product_class = get_object_or_404(
                    ProductClass, slug=product_class_slug)
            else:
                self.parent = get_object_or_404(Product, pk=parent_pk)
                self.product_class = self.parent.product_class

            return None  # success
        else:
            product = super().get_object(queryset)
            self.product_class = product.get_product_class()
            self.parent = product.parent
            return product

    # 获取上下文数据
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['product_class'] = self.product_class
        ctx['parent'] = self.parent
        ctx['title'] = self.get_page_title()

        for ctx_name, formset_class in self.formsets.items():
            if ctx_name not in ctx:
                ctx[ctx_name] = formset_class(self.product_class,
                                              self.request.user,
                                              instance=self.object)
        return ctx

    # 获取页面标题
    def get_page_title(self):
        if self.creating:
            if self.parent is None:
                return _('Create new %(product_class)s product') % {
                    'product_class': self.product_class.name}
            else:
                return _('Create new variant of %(parent_product)s') % {
                    'parent_product': self.parent.title}
        else:
            if self.object.title or not self.parent:
                return self.object.title
            else:
                return _('Editing variant of %(parent_product)s') % {
                    'parent_product': self.parent.title}

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['product_class'] = self.product_class
        kwargs['parent'] = self.parent
        return kwargs

    def process_all_forms(self, form):
        """
        Short-circuits the regular logic to have one place to have our
        logic to check all forms
        短路常规逻辑有一个地方有我们的逻辑来检查所有形式
        """
        # Need to create the product here because the inline forms need it
        # can't use commit=False because ProductForm does not support it
        # 需要在这里创建产品，因为内联表单需要它不能使用commit = False，
        # 因为ProductForm不支持它
        if self.creating and form.is_valid():
            self.object = form.save()

        formsets = {}
        for ctx_name, formset_class in self.formsets.items():
            formsets[ctx_name] = formset_class(self.product_class,
                                               self.request.user,
                                               self.request.POST,
                                               self.request.FILES,
                                               instance=self.object)

        is_valid = form.is_valid() and all([formset.is_valid()
                                            for formset in formsets.values()])

        cross_form_validation_result = self.clean(form, formsets)
        if is_valid and cross_form_validation_result:
            return self.forms_valid(form, formsets)
        else:
            return self.forms_invalid(form, formsets)

    # form_valid and form_invalid are called depending on the validation result
    # of just the product form and redisplay the form respectively return a
    # redirect to the success URL. In both cases we need to check our formsets
    # as well, so both methods do the same. process_all_forms then calls
    # forms_valid or forms_invalid respectively, which do the redisplay or
    # redirect.
    # 根据产品表单的验证结果调用form_valid和form_invalid，并重新显示表单，分别返回
    # 重定向到成功URL。 在这两种情况下，我们也需要检查我们的formset，因此两种方法
    # 都是一样的。 process_all_forms然后分别调用forms_valid或forms_invalid，它们执行
    # 重新显示或重定向。
    form_valid = form_invalid = process_all_forms

    def clean(self, form, formsets):
        """
        Perform any cross-form/formset validation. If there are errors, attach
        errors to a form or a form field so that they are displayed to the user
        and return False. If everything is valid, return True. This method will
        be called regardless of whether the individual forms are valid.

        执行任何交叉表单/表单集验证。 如果存在错误，请将错误附加到表单或表单字段，以便
        将它们显示给用户并返回False。 如果一切都有效，则返回True。 无论各个表单是否
        有效，都将调用此方法。
        """
        return True

    def forms_valid(self, form, formsets):
        """
        Save all changes and display a success url.
        When creating the first child product, this method also sets the new
        parent's structure accordingly.
        保存所有更改并显示成功URL。
        在创建第一个子产品时，此方法还会相应地设置新父项的结构。
        """
        if self.creating:
            self.handle_adding_child(self.parent)
        else:
            # a just created product was already saved in process_all_forms()
            # 刚创建的产品已保存在process_all_forms（）中
            self.object = form.save()

        # Save formsets
        # 保存表单集
        for formset in formsets.values():
            formset.save()

        return HttpResponseRedirect(self.get_success_url())

    def handle_adding_child(self, parent):
        """
        When creating the first child product, the parent product needs
        to be implicitly converted from a standalone product to a
        parent product.
        创建第一个子产品时，需要将父产品从独立产品隐式转换为父产品。
        """
        # ProductForm eagerly sets the future parent's structure to PARENT to
        # pass validation, but it's not persisted in the database. We ensure
        # it's persisted by calling save()
        # ProductForm急切地将未来的父结构设置为PARENT以通过验证，但它不会持久
        # 存储在数据库中。 我们通过调用save（）确保它是持久的
        if parent is not None:
            parent.structure = Product.PARENT
            parent.save()

    def forms_invalid(self, form, formsets):
        # delete the temporary product again
        # 再次删除临时产品
        if self.creating and self.object and self.object.pk is not None:
            self.object.delete()
            self.object = None

        messages.error(self.request,
                       _("Your submitted data was not valid - please "
                         "correct the errors below"))
        ctx = self.get_context_data(form=form, **formsets)
        return self.render_to_response(ctx)

    def get_url_with_querystring(self, url):
        url_parts = [url]
        if self.request.GET.urlencode():
            url_parts += [self.request.GET.urlencode()]
        return "?".join(url_parts)

    def get_success_url(self):
        """
        Renders a success message and redirects depending on the button:
        - Standard case is pressing "Save"; redirects to the product list
        - When "Save and continue" is pressed, we stay on the same page
        - When "Create (another) child product" is pressed, it redirects
          to a new product creation page

        呈现一个成功消息并根据按钮重定向：
        - 标准案例是按“保存”; 重定向到产品列表
        - 按“保存并继续”时，我们会保持在同一页面上
        - 当按下“创建（另一个）子产品”时，它会重定向到新的产品创建页面
        """
        msg = render_to_string(
            'dashboard/catalogue/messages/product_saved.html',
            {
                'product': self.object,
                'creating': self.creating,
                'request': self.request
            })
        messages.success(self.request, msg, extra_tags="safe noicon")

        action = self.request.POST.get('action')
        if action == 'continue':
            url = reverse(
                'dashboard:catalogue-product', kwargs={"pk": self.object.id})
        elif action == 'create-another-child' and self.parent:
            url = reverse(
                'dashboard:catalogue-product-create-child',
                kwargs={'parent_pk': self.parent.pk})
        elif action == 'create-child':
            url = reverse(
                'dashboard:catalogue-product-create-child',
                kwargs={'parent_pk': self.object.pk})
        else:
            url = reverse('dashboard:catalogue-product-list')
        return self.get_url_with_querystring(url)


# 产品删除视图
class ProductDeleteView(generic.DeleteView):
    """
    Dashboard view to delete a product. Has special logic for deleting the
    last child product.
    Supports the permission-based dashboard.
    用于删除产品的仪表板视图。 具有删除最后一个子产品的特殊逻辑。
    支持基于许可的仪表板。
    """
    template_name = 'dashboard/catalogue/product_delete.html'
    model = Product
    context_object_name = 'product'

    def get_queryset(self):
        """
        Filter products that the user doesn't have permission to update
        过滤用户无权更新的产品
        """
        return filter_products(Product.objects.all(), self.request.user)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if self.object.is_child:
            ctx['title'] = _("Delete product variant?")
        else:
            ctx['title'] = _("Delete product?")
        return ctx

    def delete(self, request, *args, **kwargs):
        # We override the core delete method and don't call super in order to
        # apply more sophisticated logic around handling child products.
        # Calling super makes it difficult to test if the product being deleted
        # is the last child.
        # 我们覆盖核心删除方法，并且不要调用super以便在处理子产品时应用更复杂的逻辑。
        # 调用super会使测试被删除的产品是否是最后一个孩子变得困难。

        self.object = self.get_object()

        # Before performing the delete, record whether this product is the last
        # child.
        # 在执行删除之前，请记录此产品是否为最后一个子产品。
        is_last_child = False
        if self.object.is_child:
            parent = self.object.parent
            is_last_child = parent.children.count() == 1

        # This also deletes any child products.
        # 这也删除了任何子产品。
        self.object.delete()

        # If the product being deleted is the last child, then pass control
        # to a method than can adjust the parent itself.
        # 如果要删除的产品是最后一个子项，则将控制权传递给方法，而不是调整父项本身。
        if is_last_child:
            self.handle_deleting_last_child(parent)

        return HttpResponseRedirect(self.get_success_url())

    def handle_deleting_last_child(self, parent):
        # If the last child product is deleted, this view defaults to turning
        # the parent product into a standalone product. While this is
        # appropriate for many scenarios, it is intentionally easily
        # overridable and not automatically done in e.g. a Product's delete()
        # method as it is more a UX helper than hard business logic.
        # 如果删除了最后一个子产品，则此视图默认将父产品转换为独立产品。 虽然这
        # 适用于许多场景，但它有意容易地可以覆盖，而不是在例如自动完成。 一个产品
        # 的delete（）方法，因为它比硬业务逻辑更像是一个UX助手。
        parent.structure = parent.STANDALONE
        parent.save()

    def get_success_url(self):
        """
        When deleting child products, this view redirects to editing the
        parent product. When deleting any other product, it redirects to the
        product list view.

        删除子产品时，此视图会重定向到编辑父产品。 删除任何其他产品时，会重定向到产品列表视图。
        """
        if self.object.is_child:
            msg = _("Deleted product variant '%s'") % self.object.get_title()
            messages.success(self.request, msg)
            return reverse(
                'dashboard:catalogue-product',
                kwargs={'pk': self.object.parent_id})
        else:
            msg = _("Deleted product '%s'") % self.object.title
            messages.success(self.request, msg)
            return reverse('dashboard:catalogue-product-list')


# 凭证警报列表视图
class StockAlertListView(generic.ListView):
    template_name = 'dashboard/catalogue/stockalert_list.html'
    model = StockAlert
    context_object_name = 'alerts'
    paginate_by = settings.OSCAR_STOCK_ALERTS_PER_PAGE

    # 获取上下文数据
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['form'] = self.form
        ctx['description'] = self.description
        return ctx

    # 获取查询集
    def get_queryset(self):
        if 'status' in self.request.GET:
            self.form = StockAlertSearchForm(self.request.GET)
            if self.form.is_valid():
                status = self.form.cleaned_data['status']
                self.description = _('Alerts with status "%s"') % status
                return self.model.objects.filter(status=status)
        else:
            self.description = _('All alerts')
            self.form = StockAlertSearchForm()
        return self.model.objects.all()


# 分类列表视图
class CategoryListView(SingleTableView):
    template_name = 'dashboard/catalogue/category_list.html'
    table_class = CategoryTable
    context_table_name = 'categories'

    def get_queryset(self):
        return Category.get_root_nodes()

    def get_context_data(self, *args, **kwargs):
        ctx = super().get_context_data(*args, **kwargs)
        ctx['child_categories'] = Category.get_root_nodes()
        return ctx


# 分类明细表视图
class CategoryDetailListView(SingleTableMixin, generic.DetailView):
    template_name = 'dashboard/catalogue/category_list.html'
    model = Category
    context_object_name = 'category'
    table_class = CategoryTable
    context_table_name = 'categories'

    def get_table_data(self):
        return self.object.get_children()

    def get_context_data(self, *args, **kwargs):
        ctx = super().get_context_data(*args, **kwargs)
        ctx['child_categories'] = self.object.get_children()
        ctx['ancestors'] = self.object.get_ancestors_and_self()
        return ctx


# 加入分类列表
class CategoryListMixin(object):

    def get_success_url(self):
        parent = self.object.get_parent()
        if parent is None:
            return reverse("dashboard:catalogue-category-list")
        else:
            return reverse("dashboard:catalogue-category-detail-list",
                           args=(parent.pk,))


# 类别创建视图
class CategoryCreateView(CategoryListMixin, generic.CreateView):
    template_name = 'dashboard/catalogue/category_form.html'
    model = Category
    form_class = CategoryForm

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = _("Add a new category")
        return ctx

    def get_success_url(self):
        messages.info(self.request, _("Category created successfully"))
        return super().get_success_url()

    # 获取初始值
    def get_initial(self):
        # set child category if set in the URL kwargs
        # 如果在URL KWAGS中设置子类
        initial = super().get_initial()
        if 'parent' in self.kwargs:
            initial['_ref_node_id'] = self.kwargs['parent']
        return initial


# 类别更新视图
class CategoryUpdateView(CategoryListMixin, generic.UpdateView):
    template_name = 'dashboard/catalogue/category_form.html'
    model = Category
    form_class = CategoryForm

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = _("Update category '%s'") % self.object.name
        return ctx

    def get_success_url(self):
        messages.info(self.request, _("Category updated successfully"))
        return super().get_success_url()


# 类别删除视图
class CategoryDeleteView(CategoryListMixin, generic.DeleteView):
    template_name = 'dashboard/catalogue/category_delete.html'
    model = Category

    def get_context_data(self, *args, **kwargs):
        ctx = super().get_context_data(*args, **kwargs)
        ctx['parent'] = self.object.get_parent()
        return ctx

    def get_success_url(self):
        messages.info(self.request, _("Category deleted successfully"))
        return super().get_success_url()


# 产品查找视图
class ProductLookupView(ObjectLookupView):
    model = Product

    def get_queryset(self):
        return self.model.browsable.all()

    def lookup_filter(self, qs, term):
        return qs.filter(Q(title__icontains=term)
                         | Q(parent__title__icontains=term))


# 产品类创建更新视图
class ProductClassCreateUpdateView(generic.UpdateView):

    template_name = 'dashboard/catalogue/product_class_form.html'
    model = ProductClass
    form_class = ProductClassForm
    product_attributes_formset = ProductAttributesFormSet

    # 处理所有表单
    def process_all_forms(self, form):
        """
        This validates both the ProductClass form and the
        ProductClassAttributes formset at once
        making it possible to display all their errors at once.

        这样可以立即验证ProductClass表单和ProductClassAttributes表
        单集，从而可以一次显示所有错误。
        """
        if self.creating and form.is_valid():
            # the object will be needed by the product_attributes_formset
            # product_attributes_formset将需要该对象
            self.object = form.save(commit=False)

        attributes_formset = self.product_attributes_formset(
            self.request.POST, self.request.FILES, instance=self.object)

        is_valid = form.is_valid() and attributes_formset.is_valid()

        if is_valid:
            return self.forms_valid(form, attributes_formset)
        else:
            return self.forms_invalid(form, attributes_formset)

    def forms_valid(self, form, attributes_formset):
        form.save()
        attributes_formset.save()

        return HttpResponseRedirect(self.get_success_url())

    def forms_invalid(self, form, attributes_formset):
        messages.error(self.request,
                       _("Your submitted data was not valid - please "
                         "correct the errors below"
                         ))
        ctx = self.get_context_data(form=form,
                                    attributes_formset=attributes_formset)
        return self.render_to_response(ctx)

    # form_valid and form_invalid are called depending on the validation result
    # of just the product class form, and return a redirect to the success URL
    # or redisplay the form, respectively. In both cases we need to check our
    # formsets as well, so both methods do the same. process_all_forms then
    # calls forms_valid or forms_invalid respectively, which do the redisplay
    # or redirect.
    # 根据产品类表单的验证结果调用form_valid和form_invalid，并分别将重定向返回到
    # 成功URL或重新显示表单。 在这两种情况下，我们也需要检查我们的formset，因此两
    # 种方法都是一样的。 process_all_forms然后分别调用forms_valid或forms_invalid，
    # 它们执行重新显示或重定向。
    form_valid = form_invalid = process_all_forms

    def get_context_data(self, *args, **kwargs):
        ctx = super().get_context_data(
            *args, **kwargs)

        if "attributes_formset" not in ctx:
            ctx["attributes_formset"] = self.product_attributes_formset(
                instance=self.object)

        ctx["title"] = self.get_title()

        return ctx


# 产品类创建视图
class ProductClassCreateView(ProductClassCreateUpdateView):

    creating = True

    def get_object(self):
        return None

    def get_title(self):
        return _("Add a new product type")

    def get_success_url(self):
        messages.info(self.request, _("Product type created successfully"))
        return reverse("dashboard:catalogue-class-list")


# 产品类更新视图
class ProductClassUpdateView(ProductClassCreateUpdateView):

    creating = False

    def get_title(self):
        return _("Update product type '%s'") % self.object.name

    def get_success_url(self):
        messages.info(self.request, _("Product type updated successfully"))
        return reverse("dashboard:catalogue-class-list")

    def get_object(self):
        product_class = get_object_or_404(ProductClass, pk=self.kwargs['pk'])
        return product_class


# 产品类别列表视图
class ProductClassListView(generic.ListView):
    template_name = 'dashboard/catalogue/product_class_list.html'
    context_object_name = 'classes'
    model = ProductClass

    def get_context_data(self, *args, **kwargs):
        ctx = super().get_context_data(*args, **kwargs)
        ctx['title'] = _("Product Types")
        return ctx


# 产品类删除视图
class ProductClassDeleteView(generic.DeleteView):
    template_name = 'dashboard/catalogue/product_class_delete.html'
    model = ProductClass
    form_class = ProductClassForm

    def get_context_data(self, *args, **kwargs):
        ctx = super().get_context_data(*args, **kwargs)
        ctx['title'] = _("Delete product type '%s'") % self.object.name
        product_count = self.object.products.count()

        if product_count > 0:
            ctx['disallow'] = True
            ctx['title'] = _("Unable to delete '%s'") % self.object.name
            messages.error(self.request,
                           _("%i products are still assigned to this type") %
                           product_count)
        return ctx

    def get_success_url(self):
        messages.info(self.request, _("Product type deleted successfully"))
        return reverse("dashboard:catalogue-class-list")


# 属性选项组创建更新视图
class AttributeOptionGroupCreateUpdateView(generic.UpdateView):

    template_name = 'dashboard/catalogue/attribute_option_group_form.html'
    model = AttributeOptionGroup
    form_class = AttributeOptionGroupForm
    attribute_option_formset = AttributeOptionFormSet

    def process_all_forms(self, form):
        """
        This validates both the AttributeOptionGroup form and the
        AttributeOptions formset at once making it possible to display all their
        errors at once.

        这样可以立即验证AttributeOptionGroup表单和AttributeOptions表单集，从
        而可以一次显示所有错误。
        """
        if self.creating and form.is_valid():
            # the object will be needed by the attribute_option_formset
            # attribute_option_formset将需要该对象
            self.object = form.save(commit=False)

        attribute_option_formset = self.attribute_option_formset(
            self.request.POST, self.request.FILES, instance=self.object)

        is_valid = form.is_valid() and attribute_option_formset.is_valid()

        if is_valid:
            return self.forms_valid(form, attribute_option_formset)
        else:
            return self.forms_invalid(form, attribute_option_formset)

    def forms_valid(self, form, attribute_option_formset):
        form.save()
        attribute_option_formset.save()

        return HttpResponseRedirect(self.get_success_url())

    def forms_invalid(self, form, attribute_option_formset):
        messages.error(self.request,
                       _("Your submitted data was not valid - please "
                         "correct the errors below"
                         ))
        ctx = self.get_context_data(form=form,
                                    attribute_option_formset=attribute_option_formset)
        return self.render_to_response(ctx)

    # form_valid and form_invalid are called depending on the validation result
    # of just the attribute option group form, and return a redirect to the
    # success URL or redisplay the form, respectively. In both cases we need to
    # check our formsets as well, so both methods do the same.
    # process_all_forms then calls forms_valid or forms_invalid respectively,
    # which do the redisplay or redirect.
    # 根据属性选项组表单的验证结果调用form_valid和form_invalid，并分别将重定向返
    # 回到成功URL或重新显示表单。 在这两种情况下，我们也需要检查我们的formset，因
    # 此两种方法都是相同的.process_all_forms然后分别调用forms_valid或forms_invalid，
    # 它们执行重新显示或重定向。
    form_valid = form_invalid = process_all_forms

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.setdefault("attribute_option_formset", self.attribute_option_formset(instance=self.object))
        ctx["title"] = self.get_title()
        return ctx

    def get_url_with_querystring(self, url):
        url_parts = [url]
        if self.request.GET.urlencode():
            url_parts += [self.request.GET.urlencode()]
        return "?".join(url_parts)


# 属性选项组创建视图
class AttributeOptionGroupCreateView(PopUpWindowCreateMixin, AttributeOptionGroupCreateUpdateView):

    creating = True

    def get_object(self):
        return None

    def get_title(self):
        return _("Add a new Attribute Option Group")

    def get_success_url(self):
        if not self.is_popup:
            messages.info(self.request, _("Attribute Option Group created successfully"))
        url = reverse("dashboard:catalogue-attribute-option-group-list")
        return self.get_url_with_querystring(url)


# 属性选项组更新视图
class AttributeOptionGroupUpdateView(PopUpWindowUpdateMixin, AttributeOptionGroupCreateUpdateView):

    creating = False

    def get_object(self):
        attribute_option_group = get_object_or_404(AttributeOptionGroup, pk=self.kwargs['pk'])
        return attribute_option_group

    def get_title(self):
        return _("Update Attribute Option Group '%s'") % self.object.name

    def get_success_url(self):
        if not self.is_popup:
            messages.info(self.request, _("Attribute Option Group updated successfully"))
        url = reverse("dashboard:catalogue-attribute-option-group-list")
        return self.get_url_with_querystring(url)


# 属性选项组列表视图
class AttributeOptionGroupListView(SingleTableView):

    template_name = 'dashboard/catalogue/attribute_option_group_list.html'
    model = AttributeOptionGroup
    table_class = AttributeOptionGroupTable
    context_table_name = 'attribute_option_groups'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['querystring'] = self.request.GET.urlencode()
        return ctx


# 属性选项组删除视图
class AttributeOptionGroupDeleteView(PopUpWindowDeleteMixin, generic.DeleteView):

    template_name = 'dashboard/catalogue/attribute_option_group_delete.html'
    model = AttributeOptionGroup
    form_class = AttributeOptionGroupForm

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        ctx['title'] = _("Delete Attribute Option Group '%s'") % self.object.name

        product_attribute_count = self.object.product_attributes.count()
        if product_attribute_count > 0:
            ctx['disallow'] = True
            ctx['title'] = _("Unable to delete '%s'") % self.object.name
            messages.error(self.request,
                           _("%i product attributes are still assigned to this attribute option group") %
                           product_attribute_count)

        ctx['http_get_params'] = self.request.GET

        return ctx

    def get_url_with_querystring(self, url):
        url_parts = [url]
        http_post_params = self.request.POST.copy()
        try:
            del http_post_params['csrfmiddlewaretoken']
        except KeyError:
            pass
        if http_post_params.urlencode():
            url_parts += [http_post_params.urlencode()]
        return "?".join(url_parts)

    def get_success_url(self):
        if not self.is_popup:
            messages.info(self.request, _("Attribute Option Group deleted successfully"))
        url = reverse("dashboard:catalogue-attribute-option-group-list")
        return self.get_url_with_querystring(url)
