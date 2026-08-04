"""
Formation Filters — django-filter filtersets for courses, enrollments, orders.
"""

import django_filters

from formation.models import Course, Enrollment, Order, get_mismatched_paid_order_ids


class CourseFilter(django_filters.FilterSet):
    category = django_filters.CharFilter(field_name='category__slug')
    level = django_filters.CharFilter()
    language = django_filters.CharFilter()
    price_min = django_filters.NumberFilter(field_name='price', lookup_expr='gte')
    price_max = django_filters.NumberFilter(field_name='price', lookup_expr='lte')
    search = django_filters.CharFilter(method='filter_search')

    class Meta:
        model = Course
        fields = ['category', 'level', 'language', 'status']

    def filter_search(self, queryset, name, value):
        """Search title and description fields."""
        from django.db.models import Q
        return queryset.filter(
            Q(title__icontains=value) | Q(description__icontains=value)
        )


class EnrollmentFilter(django_filters.FilterSet):
    status = django_filters.CharFilter()

    class Meta:
        model = Enrollment
        fields = ['status']


class OrderFilter(django_filters.FilterSet):
    status = django_filters.CharFilter()
    paymentMethod = django_filters.CharFilter()
    mismatched = django_filters.BooleanFilter(method='filter_mismatched')
    search = django_filters.CharFilter(method='filter_search')

    class Meta:
        model = Order
        fields = ['status', 'paymentMethod']

    def filter_mismatched(self, queryset, name, value):
        """Paid orders where the buyer is missing an enrollment for a purchased course."""
        mismatched_ids = get_mismatched_paid_order_ids()
        if value:
            return queryset.filter(id__in=mismatched_ids)
        return queryset.exclude(id__in=mismatched_ids)

    def filter_search(self, queryset, name, value):
        """Search by buyer email/name, order id, or payment reference."""
        from django.db.models import Q, CharField
        from django.db.models.functions import Cast
        # UUID columns need an explicit text cast before they support icontains/LIKE.
        return queryset.annotate(
            id_str=Cast('id', CharField()),
        ).filter(
            Q(user__email__icontains=value)
            | Q(user__first_name__icontains=value)
            | Q(user__last_name__icontains=value)
            | Q(id_str__icontains=value)
            | Q(paymentRef__icontains=value)
        )
