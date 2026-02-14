"""
Formation Filters — django-filter filtersets for courses, enrollments, orders.
"""

import django_filters

from formation.models import Course, Enrollment, Order


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

    class Meta:
        model = Order
        fields = ['status', 'paymentMethod']
