"""
Formation URL configuration.

All endpoints are prefixed with /api/formation/ (set in root urls.py).
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from formation import views

router = DefaultRouter()
router.register(r'categories', views.CategoryViewSet, basename='category')
router.register(r'courses', views.CourseViewSet, basename='course')
router.register(r'sections', views.SectionViewSet, basename='section')
router.register(r'lessons', views.LessonViewSet, basename='lesson')
router.register(r'enrollments', views.EnrollmentViewSet, basename='enrollment')
router.register(r'progress', views.LessonProgressViewSet, basename='progress')
router.register(r'notes', views.LessonNoteViewSet, basename='note')
router.register(r'quiz-attempts', views.QuizAttemptViewSet, basename='quiz-attempt')
router.register(r'quizzes', views.QuizViewSet, basename='quiz')
router.register(r'quiz-questions', views.QuizQuestionViewSet, basename='quiz-question')
router.register(r'orders', views.OrderViewSet, basename='order')
router.register(r'certificates', views.CertificateViewSet, basename='certificate')
router.register(r'share-tokens', views.ShareTokenViewSet, basename='share-token')

urlpatterns = [
    path('', include(router.urls)),
]
