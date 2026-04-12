"""
Formation Views — DRF ViewSets for all formation endpoints.
"""

import json
import logging
from uuid import UUID

from django.db import models as db_models
from django.db import close_old_connections
from django.db.utils import OperationalError, InterfaceError
from django.db.models import Count, Sum, Prefetch
from django.http import HttpResponse, JsonResponse, HttpRequest
from django.views import View
from rest_framework import viewsets, status, mixins
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter
from drf_spectacular.utils import extend_schema, extend_schema_view

from formation.models import (
    Category, Certificate, Course, CourseMaterial, CourseGift, CourseRating,
    CourseStatus, Enrollment,
    FinalQuiz, FinalQuizAttempt, FinalQuizAudio, GiftStatus,
    Lesson, LessonNote, LessonProgress, Order, OrderItem, OrderStatus,
    PaymentMethod, PromoCode, PromoCodeUsage,
    QuizAttempt, Quiz, QuizQuestion, Section, Module, ShareToken,
)
from formation.serializers import (
    CategorySerializer, CertificateSerializer,
    CourseDetailSerializer, CourseListSerializer, CourseWriteSerializer,
    CourseMaterialSerializer,
    CourseGiftSerializer, CourseGiftSendSerializer, CourseGiftClaimSerializer,
    CourseRatingSerializer, CourseRatingCreateSerializer,
    EnrollmentCreateSerializer, EnrollmentSerializer,
    FinalQuizSerializer, FinalQuizGenerateSerializer,
    FinalQuizSubmitSerializer, FinalQuizAttemptSerializer,
    LessonNoteSerializer, LessonProgressSerializer, LessonSerializer,
    OrderCreateSerializer, OrderSerializer,
    PromoCodeSerializer, PromoCodeValidateSerializer,
    ProgressAutosaveSerializer,
    QuizAttemptSerializer, QuizSerializer, QuizSubmitSerializer,
    QuizQuestionSerializer,
    SectionDetailSerializer, SectionSerializer, ModuleSerializer,
    ShareTokenCreateSerializer, ShareTokenSerializer,
)
from formation.permissions import IsAdminOrReadOnly, IsOwnerOrAdmin, IsEnrolledStudent
from formation.filters import CourseFilter, EnrollmentFilter, OrderFilter
from formation.services.progress_service import autosave_progress
from formation.services.quiz_service import submit_quiz, QuizLimitExceeded
from formation.services.enrollment_service import enroll_user, AlreadyEnrolled
from formation.services.sharing_service import (
    create_share_token, validate_and_consume_token,
)
from formation.services.final_quiz_service import (
    generate_final_quiz_questions, submit_final_quiz,
    FinalQuizNotConfigured, FinalQuizLimitExceeded, CourseNotCompleted as FQCourseNotCompleted,
)
from formation.chargily_service import create_chargily_checkout, client as chargily_client

logger = logging.getLogger(__name__)

ADMIN_ONLY_MSG = 'Admin only.'
NOT_ENROLLED_MSG = 'Not enrolled in this course.'
COURSE_NOT_FOUND_MSG = 'Course not found.'


def _auto_enroll_order_user(order: Order) -> None:
    """Idempotently enroll order owner into all courses in the order."""
    courses = [item.course for item in order.items.select_related('course')]
    for course in courses:
        try:
            enroll_user(order.user, course)
        except AlreadyEnrolled:
            pass


def _checkout_is_paid(checkout_payload: dict) -> bool:
    """Best-effort status detection across Chargily payload formats."""
    paid_values = {'paid', 'succeeded', 'success', 'completed'}

    candidates = [
        checkout_payload.get('status'),
        checkout_payload.get('payment_status'),
        checkout_payload.get('checkout_status'),
    ]

    data = checkout_payload.get('data')
    if isinstance(data, dict):
        candidates.extend([
            data.get('status'),
            data.get('payment_status'),
            data.get('checkout_status'),
        ])

    for value in candidates:
        if isinstance(value, str) and value.strip().lower() in paid_values:
            return True
    return False


class DBRetryReadMixin:
    """Retry read operations once after resetting stale DB connections."""

    def _run_with_db_retry(self, callback):
        try:
            return callback()
        except (OperationalError, InterfaceError):
            close_old_connections()
            return callback()


# ─── Category ────────────────────────────────────────────────────────────────

@extend_schema_view(
    list=extend_schema(summary='List all categories'),
    retrieve=extend_schema(summary='Retrieve a category'),
)
class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [IsAdminOrReadOnly]
    lookup_field = 'slug'


# ─── Course ──────────────────────────────────────────────────────────────────

@extend_schema_view(
    list=extend_schema(summary='List courses (catalog)'),
    retrieve=extend_schema(summary='Retrieve course detail'),
)
class CourseViewSet(DBRetryReadMixin, viewsets.ModelViewSet):
    permission_classes = [IsAdminOrReadOnly]
    lookup_field = 'slug'
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = CourseFilter
    ordering_fields = ['date', 'price', 'rating', 'students', 'created_at']
    ordering = ['-date']

    def get_queryset(self):
        # Pre-annotate nested modules and sections to avoid N+1 queries
        # in serializers when returning course content trees.
        annotated_modules = Module.objects.annotate(
            _lessons_count=Count('lessons', distinct=True),
            _total_duration_seconds=Sum('lessons__duration_seconds'),
        ).prefetch_related('lessons')

        annotated_sections = Section.objects.annotate(
            _modules_count=Count('modules', distinct=True),
            _total_duration_seconds=Sum('modules__lessons__duration_seconds'),
        ).prefetch_related(
            Prefetch('modules', queryset=annotated_modules),
            'quiz__questions',
        )

        qs = Course.objects.select_related('category').prefetch_related(
            Prefetch('sections', queryset=annotated_sections),
            'materials',
        ).annotate(
            # Pre-compute totals used by CourseDetailSerializer
            _total_modules=Count('sections__modules', distinct=True),
            _total_slides=Count('sections__modules__lessons', distinct=True),
            _total_quiz_questions=Count(
                'sections__quiz__questions', distinct=True,
            ),
        )
        # Non-admin users only see published courses
        if not (self.request.user.is_authenticated and self.request.user.is_admin):
            qs = qs.filter(status=CourseStatus.PUBLISHED)
        return qs

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return CourseDetailSerializer
        if self.action in ('create', 'update', 'partial_update'):
            return CourseWriteSerializer
        return CourseListSerializer

    def list(self, request, *args, **kwargs):
        return self._run_with_db_retry(
            lambda: super(CourseViewSet, self).list(request, *args, **kwargs)
        )

    def retrieve(self, request, *args, **kwargs):
        return self._run_with_db_retry(
            lambda: super(CourseViewSet, self).retrieve(request, *args, **kwargs)
        )

    def destroy(self, request, *args, **kwargs):
        """Delete a course, handling ProtectedError from related OrderItems."""
        instance = self.get_object()
        try:
            self.perform_destroy(instance)
        except db_models.ProtectedError:
            return Response(
                {'detail': 'Cannot delete this course because it has existing orders. '
                           'Please remove or archive the related orders first.'},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        summary='Rate a course (enrolled users only)',
        request=CourseRatingCreateSerializer,
        responses=CourseRatingSerializer,
    )
    @action(detail=True, methods=['post'], url_path='rate',
            permission_classes=[IsAuthenticated])
    def rate(self, request, slug=None):
        """Submit or update a course rating. User must be enrolled."""
        course = self.get_object()
        user = request.user

        # Check enrollment
        if not Enrollment.objects.filter(user=user, course=course).exists():
            return Response(
                {'detail': 'You must be enrolled in this course to rate it.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        ser = CourseRatingCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        rating_obj, created = CourseRating.objects.update_or_create(
            user=user,
            course=course,
            defaults={
                'rating': ser.validated_data['rating'],
                'review_text': ser.validated_data.get('review_text', ''),
            },
        )

        return Response(
            CourseRatingSerializer(rating_obj).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @extend_schema(summary='Get ratings for a course')
    @action(detail=True, methods=['get'], url_path='ratings',
            permission_classes=[AllowAny])
    def ratings(self, request, slug=None):
        """List all ratings for a course."""
        course = self.get_object()
        ratings = CourseRating.objects.filter(course=course).select_related('user')
        return Response(CourseRatingSerializer(ratings, many=True).data)

    @extend_schema(summary='Preview Course Zip (Admin)')
    @action(detail=False, methods=['post'], url_path='import-zip-preview', permission_classes=[IsAdminOrReadOnly])
    def import_zip_preview(self, request):
        if not request.user.is_staff:
            return Response({'detail': ADMIN_ONLY_MSG}, status=status.HTTP_403_FORBIDDEN)
            
        zip_file = request.FILES.get('zip_file')
        if not zip_file:
            return Response({'detail': 'No zip_file provided.'}, status=status.HTTP_400_BAD_REQUEST)
            
        import tempfile, os
        from formation.services.zip_import_service import parse_zip_plan
        
        fd, temp_zip_path = tempfile.mkstemp(suffix='.zip', prefix='ooskills_up_')
        try:
            with os.fdopen(fd, 'wb') as f:
                for chunk in zip_file.chunks():
                    f.write(chunk)
            plan = parse_zip_plan(temp_zip_path)
        except Exception as e:
            return Response({'detail': f'Error parsing zip: {str(e)}'}, status=status.HTTP_400_BAD_REQUEST)
        finally:
            if temp_zip_path and os.path.exists(temp_zip_path):
                os.remove(temp_zip_path)
                
        return Response(plan, status=status.HTTP_200_OK)

    @extend_schema(summary='Confirm Import Course Zip (Admin)')
    @action(detail=False, methods=['post'], url_path='import-zip', permission_classes=[IsAdminOrReadOnly])
    def import_zip_confirm(self, request):
        if not request.user.is_staff:
            return Response({'detail': ADMIN_ONLY_MSG}, status=status.HTTP_403_FORBIDDEN)
            
        zip_file = request.FILES.get('zip_file')
        category_id = request.data.get('category_id')
        instructor_id = request.data.get('instructor_id')
        
        if not zip_file:
            return Response({'detail': 'No zip_file provided.'}, status=status.HTTP_400_BAD_REQUEST)
            
        import tempfile, os
        from formation.services.zip_import_service import import_course_from_zip
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        fd, temp_zip_path = tempfile.mkstemp(suffix='.zip', prefix='ooskills_up_')
        
        category = Category.objects.filter(id=category_id).first() if category_id else None
        instructor = User.objects.filter(id=instructor_id).first() if instructor_id else None
        
        try:
            with os.fdopen(fd, 'wb') as f:
                for chunk in zip_file.chunks():
                    f.write(chunk)
            
            # Do not keep one long transaction open across zip extraction/parsing.
            # Long-running imports can hit DB/pool timeouts before all lesson inserts.
            course = import_course_from_zip(temp_zip_path, category, instructor)
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        finally:
            if temp_zip_path and os.path.exists(temp_zip_path):
                os.remove(temp_zip_path)
                
        return Response(CourseDetailSerializer(course, context={'request': request}).data, status=status.HTTP_201_CREATED)


# ─── Course Material ─────────────────────────────────────────────────────────

@extend_schema_view(
    list=extend_schema(summary='List course materials'),
    create=extend_schema(summary='Upload a course material'),
)
class CourseMaterialViewSet(viewsets.ModelViewSet):
    """
    Course materials CRUD (admin-only for write).

    Filter by course: GET /api/formation/course-materials/?course=<course-id>
    """
    serializer_class = CourseMaterialSerializer
    permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        qs = CourseMaterial.objects.select_related('course')
        course_id = self.request.query_params.get('course')
        if course_id:
            qs = qs.filter(course_id=course_id)
        return qs

@extend_schema_view(
    list=extend_schema(summary='List sections (optionally filter by course slug)'),
    retrieve=extend_schema(summary='Retrieve a section with lessons'),
)
class SectionViewSet(DBRetryReadMixin, viewsets.ModelViewSet):
    """
    Sections API.

    List: GET /api/formation/sections/?course=<course-slug-or-id>
    Detail: GET /api/formation/sections/<id>/
    """
    permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        annotated_modules = Module.objects.annotate(
            _lessons_count=Count('lessons', distinct=True),
            _total_duration_seconds=Sum('lessons__duration_seconds'),
        ).prefetch_related('lessons')

        qs = Section.objects.select_related('course').prefetch_related(
            Prefetch('modules', queryset=annotated_modules),
            'quiz__questions',
        ).annotate(
            _modules_count=Count('modules', distinct=True),
            _total_duration_seconds=Sum('modules__lessons__duration_seconds'),
        )
        course_ref = self.request.query_params.get('course')
        if course_ref:
            try:
                course_uuid = UUID(str(course_ref))
            except (TypeError, ValueError):
                qs = qs.filter(course__slug=course_ref)
            else:
                qs = qs.filter(course_id=course_uuid)
        return qs.order_by('sequence')

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return SectionDetailSerializer
        return SectionDetailSerializer

    def list(self, request, *args, **kwargs):
        return self._run_with_db_retry(
            lambda: super(SectionViewSet, self).list(request, *args, **kwargs)
        )

    def retrieve(self, request, *args, **kwargs):
        return self._run_with_db_retry(
            lambda: super(SectionViewSet, self).retrieve(request, *args, **kwargs)
        )


# ─── Module ──────────────────────────────────────────────────────────────────

@extend_schema_view(
    list=extend_schema(summary='List modules (optionally filter by section)'),
    retrieve=extend_schema(summary='Retrieve a module with lessons'),
)
class ModuleViewSet(DBRetryReadMixin, viewsets.ModelViewSet):
    """
    Modules API.

    List: GET /api/formation/modules/?section=<section-id>
    Detail: GET /api/formation/modules/<id>/
    """
    permission_classes = [IsAdminOrReadOnly]
    serializer_class = ModuleSerializer

    def get_queryset(self):
        qs = Module.objects.select_related('section__course').prefetch_related(
            'lessons',
        ).annotate(
            _lessons_count=Count('lessons'),
            _total_duration_seconds=Sum('lessons__duration_seconds'),
        )
        section_id = self.request.query_params.get('section')
        if section_id:
            qs = qs.filter(section_id=section_id)
        return qs.order_by('sequence')

    def list(self, request, *args, **kwargs):
        return self._run_with_db_retry(
            lambda: super(ModuleViewSet, self).list(request, *args, **kwargs)
        )

    def retrieve(self, request, *args, **kwargs):
        return self._run_with_db_retry(
            lambda: super(ModuleViewSet, self).retrieve(request, *args, **kwargs)
        )

# ─── Lesson ──────────────────────────────────────────────────────────────────

class LessonViewSet(DBRetryReadMixin, viewsets.ModelViewSet):
    """
    Lesson CRUD. Audio uploads via the audioUrl FileField go
    directly to Supabase Storage (audios/<course_id>/).
    """
    serializer_class = LessonSerializer
    permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        user = self.request.user
        qs = Lesson.objects.select_related('module__section__course')
        if not (user.is_authenticated and user.is_admin):
            if not user.is_authenticated:
                return qs.none()
            enrolled_courses = Enrollment.objects.filter(
                user=user
            ).values_list('course_id', flat=True)
            qs = qs.filter(module__section__course_id__in=enrolled_courses)
        return qs

    def list(self, request, *args, **kwargs):
        return self._run_with_db_retry(
            lambda: super(LessonViewSet, self).list(request, *args, **kwargs)
        )

    def retrieve(self, request, *args, **kwargs):
        return self._run_with_db_retry(
            lambda: super(LessonViewSet, self).retrieve(request, *args, **kwargs)
        )

# ─── Quiz ────────────────────────────────────────────────────────────────────

class QuizViewSet(viewsets.ModelViewSet):
    """
    Quiz CRUD.

    Filter by section: GET /api/formation/quizzes/?section=<section-id>
    """
    serializer_class = QuizSerializer
    permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        qs = Quiz.objects.select_related(
            'section__course',
        ).prefetch_related('questions')
        section_id = self.request.query_params.get('section')
        if section_id:
            qs = qs.filter(section_id=section_id)
        return qs


# ─── Quiz Question ───────────────────────────────────────────────────────────

class QuizQuestionViewSet(viewsets.ModelViewSet):
    """
    QuizQuestion CRUD.

    Filter by quiz: GET /api/formation/quiz-questions/?quiz=<quiz-id>
    """
    serializer_class = QuizQuestionSerializer
    permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        qs = QuizQuestion.objects.select_related('quiz')
        quiz_id = self.request.query_params.get('quiz')
        if quiz_id:
            qs = qs.filter(quiz_id=quiz_id)
        return qs


# ─── Enrollment ──────────────────────────────────────────────────────────────

@extend_schema_view(
    list=extend_schema(summary='List my enrollments'),
    create=extend_schema(summary='Enroll in a course'),
)
class EnrollmentViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_class = EnrollmentFilter

    def get_queryset(self):
        return Enrollment.objects.filter(user=self.request.user).select_related('course')

    def get_serializer_class(self):
        if self.action == 'create':
            return EnrollmentCreateSerializer
        return EnrollmentSerializer

    def create(self, request, *args, **kwargs):
        ser = EnrollmentCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        try:
            course = Course.objects.get(id=ser.validated_data['courseId'])
        except Course.DoesNotExist:
            return Response(
                {'detail': COURSE_NOT_FOUND_MSG},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            enrollment = enroll_user(request.user, course)
        except AlreadyEnrolled as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_409_CONFLICT,
            )

        return Response(
            EnrollmentSerializer(enrollment).data,
            status=status.HTTP_201_CREATED,
        )


# ─── Lesson Progress ────────────────────────────────────────────────────────

@extend_schema_view(
    list=extend_schema(summary='List progress for an enrollment'),
    create=extend_schema(summary='Autosave lesson progress'),
)
class LessonProgressViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = LessonProgressSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return LessonProgress.objects.filter(
            enrollment__user=self.request.user,
        )

    @extend_schema(request=ProgressAutosaveSerializer, responses=LessonProgressSerializer)
    def create(self, request, *args, **kwargs):
        ser = ProgressAutosaveSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        lesson_id = ser.validated_data['lesson_id']
        try:
            lesson = Lesson.objects.select_related('module__section__course').get(id=lesson_id)
        except Lesson.DoesNotExist:
            return Response(
                {'detail': 'Lesson not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            enrollment = Enrollment.objects.get(
                user=request.user, course=lesson.module.section.course,
            )
        except Enrollment.DoesNotExist:
            return Response(
                {'detail': NOT_ENROLLED_MSG},
                status=status.HTTP_403_FORBIDDEN,
            )

        progress = autosave_progress(
            enrollment=enrollment,
            lesson=lesson,
            current_slide=ser.validated_data['current_slide'],
            last_position=ser.validated_data['last_position'],
            time_spent_delta=ser.validated_data['time_spent_delta'],
            completed=ser.validated_data['completed'],
        )

        return Response(
            LessonProgressSerializer(progress).data,
            status=status.HTTP_200_OK,
        )


# ─── Lesson Notes ────────────────────────────────────────────────────────────

class LessonNoteViewSet(viewsets.ModelViewSet):
    serializer_class = LessonNoteSerializer
    permission_classes = [IsAuthenticated, IsEnrolledStudent]

    def get_queryset(self):
        return LessonNote.objects.filter(
            enrollment__user=self.request.user,
        )

    def perform_create(self, serializer):
        lesson = serializer.validated_data['lesson']
        enrollment = Enrollment.objects.get(
            user=self.request.user,
            course=lesson.module.section.course,
        )
        serializer.save(enrollment=enrollment)


# ─── Quiz Attempt ────────────────────────────────────────────────────────────

@extend_schema_view(
    list=extend_schema(summary='List my quiz attempts'),
    create=extend_schema(summary='Submit a quiz attempt'),
)
class QuizAttemptViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return QuizAttempt.objects.filter(
            enrollment__user=self.request.user,
        ).select_related('quiz', 'enrollment')

    def get_serializer_class(self):
        if self.action == 'create':
            return QuizSubmitSerializer
        return QuizAttemptSerializer

    @extend_schema(request=QuizSubmitSerializer, responses=QuizAttemptSerializer)
    def create(self, request, *args, **kwargs):
        ser = QuizSubmitSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        try:
            quiz = Quiz.objects.get(id=ser.validated_data['quiz_id'])
        except Quiz.DoesNotExist:
            return Response(
                {'detail': 'Quiz not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            enrollment = Enrollment.objects.get(
                user=request.user,
                course=quiz.section.course,
            )
        except Enrollment.DoesNotExist:
            return Response(
                {'detail': NOT_ENROLLED_MSG},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            attempt = submit_quiz(
                enrollment=enrollment,
                quiz=quiz,
                answers=ser.validated_data['answers'],
            )
        except QuizLimitExceeded as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        except ValueError as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            QuizAttemptSerializer(attempt).data,
            status=status.HTTP_201_CREATED,
        )


# ─── Order ───────────────────────────────────────────────────────────────────

@extend_schema_view(
    list=extend_schema(summary='List my orders'),
    create=extend_schema(summary='Create an order'),
)
class OrderViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticated, IsOwnerOrAdmin]
    filter_backends = [DjangoFilterBackend]
    filterset_class = OrderFilter

    def get_queryset(self):
        user = self.request.user
        if user.is_admin:
            return Order.objects.all().prefetch_related('items__course')
        return Order.objects.filter(user=user).prefetch_related('items__course')

    def get_serializer_class(self):
        if self.action == 'create':
            return OrderCreateSerializer
        return OrderSerializer

    @extend_schema(request=OrderCreateSerializer, responses=OrderSerializer)
    def create(self, request, *args, **kwargs):
        ser = OrderCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        course_ids = ser.validated_data['course_ids']
        courses = Course.objects.filter(id__in=course_ids)
        if courses.count() != len(course_ids):
            return Response(
                {'detail': 'One or more courses not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        total = sum(c.price for c in courses)
        order = Order.objects.create(
            user=request.user,
            total=total,
            paymentMethod=ser.validated_data['paymentMethod'],
            paymentRef=ser.validated_data.get('paymentRef', ''),
        )

        for course in courses:
            OrderItem.objects.create(
                order=order, course=course, price=course.price,
            )

        # Free order → mark paid immediately and auto-enroll
        if total == 0:
            order.status = OrderStatus.PAID
            order.save(update_fields=['status'])
            for course in courses:
                try:
                    enroll_user(request.user, course)
                except AlreadyEnrolled:
                    pass
            return Response(
                OrderSerializer(order).data,
                status=status.HTTP_201_CREATED,
            )

        # Paid order → create Chargily checkout and return checkout_url
        try:
            payment_method = ser.validated_data['paymentMethod']
            # Pass the first course slug for the success redirect
            first_course_slug = courses.first().slug if courses.exists() else ''
            chargily_id, checkout_url = create_chargily_checkout(
                order, payment_method=payment_method, course_slug=first_course_slug,
            )
            order.chargily_checkout_id = chargily_id
            order.checkout_url = checkout_url
            order.save(update_fields=['chargily_checkout_id', 'checkout_url'])
        except Exception as e:
            logger.error(f'Chargily checkout creation failed: {e}')
            order.status = OrderStatus.FAILED
            order.save(update_fields=['status'])
            return Response(
                {'detail': f'Payment initialization failed: {str(e)}'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        data = OrderSerializer(order).data
        data['checkout_url'] = checkout_url
        return Response(data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='confirm-payment')
    def confirm_payment(self, request, pk=None):
        """
        Confirm payment status for an order and auto-enroll as fallback.

        Useful when the user lands on success page before webhook processing.
        """
        order = self.get_object()

        if order.status == OrderStatus.PAID:
            _auto_enroll_order_user(order)
            return Response(OrderSerializer(order).data, status=status.HTTP_200_OK)

        if not order.chargily_checkout_id:
            return Response(
                {'detail': 'Order has no checkout reference.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            checkout = chargily_client.retrieve_checkout(order.chargily_checkout_id)
        except Exception as e:
            logger.warning(f'Chargily checkout retrieve failed for order {order.id}: {e}')
            return Response(
                {'detail': 'Unable to verify payment at the moment. Please retry shortly.'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        if _checkout_is_paid(checkout):
            order.status = OrderStatus.PAID

            payment_ref = ''
            if isinstance(checkout, dict):
                payment_ref = str(
                    checkout.get('payment_id')
                    or checkout.get('id')
                    or ''
                )
            if payment_ref:
                order.paymentRef = payment_ref
                order.save(update_fields=['status', 'paymentRef', 'updated_at'])
            else:
                order.save(update_fields=['status', 'updated_at'])

            _auto_enroll_order_user(order)
            return Response(OrderSerializer(order).data, status=status.HTTP_200_OK)

        return Response(
            {
                'detail': 'Payment not confirmed yet.',
                'order_status': order.status,
            },
            status=status.HTTP_202_ACCEPTED,
        )


# ─── Final Quiz ─────────────────────────────────────────────────────────────────────

@extend_schema_view(
    list=extend_schema(summary='List final quiz config for a course'),
)
class FinalQuizViewSet(viewsets.GenericViewSet):
    """Final quiz endpoints for certificate generation."""
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'generate':
            return FinalQuizGenerateSerializer
        if self.action == 'submit':
            return FinalQuizSubmitSerializer
        return FinalQuizSerializer

    @action(detail=False, methods=['get'], url_path='config')
    def config(self, request):
        """Get final quiz config for a course.

        GET /api/formation/final-quiz/config/?course=<slug>
        """
        course_slug = request.query_params.get('course')
        if not course_slug:
            return Response(
                {'detail': 'course query parameter is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            final_quiz = FinalQuiz.objects.select_related('course').get(
                course__slug=course_slug,
            )
        except FinalQuiz.DoesNotExist:
            return Response(
                {'detail': 'No final quiz configured for this course.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = FinalQuizSerializer(final_quiz, context={'request': request})
        return Response(serializer.data)

    @action(detail=False, methods=['post'], url_path='generate')
    def generate(self, request):
        """Generate random questions for a final quiz attempt.

        POST /api/formation/final-quiz/generate/
        Body: { course_id }
        """
        ser = FinalQuizGenerateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        try:
            enrollment = Enrollment.objects.get(
                user=request.user, course_id=ser.validated_data['course_id'],
            )
        except Enrollment.DoesNotExist:
            return Response(
                {'detail': NOT_ENROLLED_MSG},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            questions = generate_final_quiz_questions(enrollment)
        except FQCourseNotCompleted as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except FinalQuizNotConfigured as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_404_NOT_FOUND,
            )
        except FinalQuizLimitExceeded as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        return Response({'questions': questions})

    @action(detail=False, methods=['post'], url_path='submit')
    def submit(self, request):
        """Submit final quiz answers.

        POST /api/formation/final-quiz/submit/
        Body: { course_id, question_ids, answers }

        Returns the attempt result, including whether a certificate was issued.
        """
        ser = FinalQuizSubmitSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        try:
            enrollment = Enrollment.objects.get(
                user=request.user, course_id=ser.validated_data['course_id'],
            )
        except Enrollment.DoesNotExist:
            return Response(
                {'detail': NOT_ENROLLED_MSG},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            question_ids = [str(qid) for qid in ser.validated_data['question_ids']]
            attempt = submit_final_quiz(
                enrollment=enrollment,
                answers=ser.validated_data['answers'],
                question_ids=question_ids,
            )
        except FinalQuizNotConfigured as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_404_NOT_FOUND,
            )
        except FinalQuizLimitExceeded as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        except ValueError as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = FinalQuizAttemptSerializer(attempt).data

        # If passed, include certificate info
        if attempt.passed:
            try:
                cert = Certificate.objects.get(
                    user=request.user, course=enrollment.course,
                )
                result['certificate'] = CertificateSerializer(cert).data
            except Certificate.DoesNotExist:
                pass
        else:
            # Include motivation audio URL based on score percentage
            try:
                fq = FinalQuiz.objects.get(course=enrollment.course)
                score_pct = float(attempt.score)

                # Try percentage-based audio entries first
                matched_audio = FinalQuizAudio.objects.filter(
                    final_quiz=fq,
                    min_percentage__lte=score_pct,
                    max_percentage__gte=score_pct,
                ).first()

                if matched_audio and matched_audio.audio:
                    result['motivation_audio_url'] = matched_audio.audio.url
                    result['audio_label'] = matched_audio.label
                elif fq.motivation_audio:
                    # Fallback to legacy single audio
                    result['motivation_audio_url'] = fq.motivation_audio.url
            except FinalQuiz.DoesNotExist:
                pass

        return Response(result, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'], url_path='my-attempts')
    def my_attempts(self, request):
        """List final quiz attempts for the current user.

        GET /api/formation/final-quiz/my-attempts/
        """
        attempts = FinalQuizAttempt.objects.filter(
            enrollment__user=request.user,
        ).select_related('final_quiz', 'enrollment').order_by('-submitted_at')
        serializer = FinalQuizAttemptSerializer(attempts, many=True)
        return Response(serializer.data)

    # ── Admin CRUD ────────────────────────────────────────────────

    @action(detail=False, methods=['get'], url_path='admin/get')
    def admin_get(self, request):
        """
        Get the final quiz for a course (admin only).

        GET /api/formation/final-quiz/admin/get/?course_id=<uuid>
        """
        if not (request.user.is_staff or getattr(request.user, 'role', '') in ('ADMIN', 'SUPER_ADMIN')):
            return Response({'detail': ADMIN_ONLY_MSG}, status=status.HTTP_403_FORBIDDEN)

        course_id = request.query_params.get('course_id')
        if not course_id:
            return Response({'detail': 'course_id query parameter required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            fq = FinalQuiz.objects.get(course_id=course_id)
        except FinalQuiz.DoesNotExist:
            return Response({'detail': 'No final quiz configured.'}, status=status.HTTP_404_NOT_FOUND)

        return Response(FinalQuizSerializer(fq, context={'request': request}).data)

    @action(detail=False, methods=['post'], url_path='admin/upsert')
    def admin_upsert(self, request):
        """
        Create or update the final quiz for a course (admin only).

        POST /api/formation/final-quiz/admin/upsert/
        Body (multipart/form-data or JSON): {
            course_id: UUID,
            title: str,                   # optional
            num_questions: int,           # how many Q's drawn per attempt
            pass_threshold: int,          # 0–100
            max_attempts: int,
            xp_reward: int,
            motivation_audio: File,       # optional audio file
        }
        """
        if not (request.user.is_staff or getattr(request.user, 'role', '') in ('ADMIN', 'SUPER_ADMIN')):
            return Response({'detail': ADMIN_ONLY_MSG}, status=status.HTTP_403_FORBIDDEN)

        course_id = request.data.get('course_id')
        if not course_id:
            return Response({'detail': 'course_id is required.'}, status=status.HTTP_400_BAD_REQUEST)

        from formation.models import Course as CourseModel
        try:
            course = CourseModel.objects.get(id=course_id)
        except CourseModel.DoesNotExist:
            return Response({'detail': COURSE_NOT_FOUND_MSG}, status=status.HTTP_404_NOT_FOUND)

        defaults = {
            'title': request.data.get('title', 'Final Quiz'),
            'num_questions': int(request.data.get('num_questions', 10)),
            'pass_threshold': int(request.data.get('pass_threshold', 70)),
            'max_attempts': int(request.data.get('max_attempts', 3)),
            'xp_reward': int(request.data.get('xp_reward', 50)),
        }

        fq, created = FinalQuiz.objects.update_or_create(
            course=course,
            defaults=defaults,
        )

        self._handle_legacy_audio(request, fq)
        entries_data = self._extract_audio_entries_data(request)
        self._update_audio_entries(request, fq, entries_data)

        return Response(
            FinalQuizSerializer(fq, context={'request': request}).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def _handle_legacy_audio(self, request, fq):
        if 'motivation_audio' in request.FILES:
            fq.motivation_audio = request.FILES['motivation_audio']
            fq.save(update_fields=['motivation_audio'])
        elif request.data.get('clear_motivation_audio') == 'true':
            fq.motivation_audio = ''
            fq.save(update_fields=['motivation_audio'])

    def _extract_audio_entries_data(self, request):
        entries_data = []
        idx = 0
        while True:
            min_key = f'audio_entries[{idx}].min_percentage'
            max_key = f'audio_entries[{idx}].max_percentage'
            label_key = f'audio_entries[{idx}].label'
            audio_key = f'audio_entries[{idx}].audio'
            existing_id_key = f'audio_entries[{idx}].id'

            if min_key not in request.data and max_key not in request.data:
                break

            entries_data.append({
                'id': request.data.get(existing_id_key, ''),
                'min_percentage': int(request.data.get(min_key, 0)),
                'max_percentage': int(request.data.get(max_key, 100)),
                'label': request.data.get(label_key, ''),
                'audio_file': request.FILES.get(audio_key),
            })
            idx += 1
        return entries_data

    def _update_audio_entries(self, request, fq, entries_data):
        if not entries_data and request.data.get('clear_audio_entries') != 'true':
            return

        keep_ids = set()
        for entry in entries_data:
            obj_id = self._process_single_audio_entry(entry, fq)
            if obj_id:
                keep_ids.add(obj_id)

        # Delete entries that were removed by admin
        FinalQuizAudio.objects.filter(final_quiz=fq).exclude(id__in=keep_ids).delete()

    def _process_single_audio_entry(self, entry, fq):
        existing_id = entry.get('id', '')
        if existing_id:
            # Update existing entry
            try:
                obj = FinalQuizAudio.objects.get(id=existing_id, final_quiz=fq)
                obj.min_percentage = entry['min_percentage']
                obj.max_percentage = entry['max_percentage']
                obj.label = entry['label']
                if entry['audio_file']:
                    obj.audio = entry['audio_file']
                obj.save()
                return str(obj.id)
            except FinalQuizAudio.DoesNotExist:
                existing_id = ''  # treat as new

        if not existing_id:
            # Create new entry
            obj = FinalQuizAudio.objects.create(
                final_quiz=fq,
                min_percentage=entry['min_percentage'],
                max_percentage=entry['max_percentage'],
                label=entry['label'],
            )
            if entry['audio_file']:
                obj.audio = entry['audio_file']
                obj.save(update_fields=['audio'])
            return str(obj.id)

    @action(detail=False, methods=['delete'], url_path='admin/delete')
    def admin_delete(self, request):
        """
        Delete the final quiz for a course (admin only).

        DELETE /api/formation/final-quiz/admin/delete/?course_id=<uuid>
        """
        if not (request.user.is_staff or getattr(request.user, 'role', '') in ('ADMIN', 'SUPER_ADMIN')):
            return Response({'detail': ADMIN_ONLY_MSG}, status=status.HTTP_403_FORBIDDEN)

        course_id = request.query_params.get('course_id')
        if not course_id:
            return Response({'detail': 'course_id query parameter required.'}, status=status.HTTP_400_BAD_REQUEST)

        deleted, _ = FinalQuiz.objects.filter(course_id=course_id).delete()
        if not deleted:
            return Response({'detail': 'No final quiz found.'}, status=status.HTTP_404_NOT_FOUND)

        return Response(status=status.HTTP_204_NO_CONTENT)



# ─── Certificate ─────────────────────────────────────────────────────────────────

@extend_schema_view(
    list=extend_schema(summary='List my certificates'),
    retrieve=extend_schema(summary='Retrieve a certificate'),
)
class CertificateViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CertificateSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrAdmin]

    def get_queryset(self):
        return Certificate.objects.filter(user=self.request.user).select_related('course', 'user')

    @action(detail=False, methods=['get'], url_path='verify/(?P<code>[^/.]+)')
    def verify(self, request, code=None):
        """Public endpoint to verify a certificate by its code."""
        try:
            cert = Certificate.objects.select_related('course', 'user').get(code=code)
        except Certificate.DoesNotExist:
            return Response(
                {'detail': 'Certificate not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(CertificateSerializer(cert).data)

    @action(detail=False, methods=['get'], url_path='merged')
    def merged(self, request):
        """
        Return all the authenticated user's certificates shaped for
        MergedCertificateTemplate.

        GET /api/formation/certificates/merged/

        Response:
        {
            "code": "MERGED-<short_user_id>",
            "student_name": "...",
            "courses": [
                {"course_name": "...", "score": 85},
                ...
            ],
            "issued_at": "<ISO datetime of the latest certificate>"
        }

        Returns 400 if the user has fewer than 2 certificates.
        """
        certs = Certificate.objects.filter(
            user=request.user
        ).select_related('course', 'user').order_by('-issuedAt')

        if certs.count() < 2:
            return Response(
                {'detail': 'At least 2 certificates are required for a merged badge.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = request.user
        student_name = (
            getattr(user, 'full_name', '') or
            f'{user.first_name} {user.last_name}'.strip() or
            user.email.split('@')[0]
        )

        courses = [
            {
                'course_name': cert.course.title,
                'score': int(cert.score),
            }
            for cert in certs
        ]

        latest = certs.first()
        short_id = str(user.id)[:8].upper()

        return Response({
            'code': f'MERGED-{short_id}',
            'student_name': student_name,
            'courses': courses,
            'issued_at': latest.issuedAt.isoformat(),
        })

    def get_permissions(self):
        if self.action == 'verify':
            return [AllowAny()]
        return super().get_permissions()


# ─── Share Token ─────────────────────────────────────────────────────────────

class ShareTokenViewSet(viewsets.ModelViewSet):
    serializer_class = ShareTokenSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrAdmin]

    def get_queryset(self):
        user = self.request.user
        if user.is_admin:
            return ShareToken.objects.all().select_related('course')
        return ShareToken.objects.filter(created_by=user).select_related('course')

    def get_serializer_class(self):
        if self.action == 'create':
            return ShareTokenCreateSerializer
        return ShareTokenSerializer

    @extend_schema(request=ShareTokenCreateSerializer, responses=ShareTokenSerializer)
    def create(self, request, *args, **kwargs):
        ser = ShareTokenCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        try:
            course = Course.objects.get(id=ser.validated_data['course_id'])
        except Course.DoesNotExist:
            return Response(
                {'detail': COURSE_NOT_FOUND_MSG},
                status=status.HTTP_404_NOT_FOUND,
            )

        token = create_share_token(
            course=course,
            user=request.user,
            visibility=ser.validated_data['visibility'],
            max_uses=ser.validated_data['max_uses'],
            expires_in_days=ser.validated_data.get('expires_in_days'),
        )

        return Response(
            ShareTokenSerializer(token).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=['post'], url_path='validate')
    def validate_token(self, request):
        """Validate and consume a share token."""
        token_str = request.data.get('token')
        if not token_str:
            return Response(
                {'detail': 'Token is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        share = validate_and_consume_token(token_str)
        if not share:
            return Response(
                {'detail': 'Invalid or expired token.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(ShareTokenSerializer(share).data)


# ─── Chargily Webhook ────────────────────────────────────────────────────────

class ChargilyWebhookView(View):
    """
    Handles Chargily Pay V2 webhooks.

    Chargily POSTs to this endpoint when a checkout status changes.
    The view validates the HMAC signature, finds the matching order,
    and updates its status (+ auto-enrolls on payment success).
    """

    def post(self, request: HttpRequest, *args, **kwargs):
        signature = request.headers.get('signature')
        payload = request.body.decode('utf-8')

        if not signature:
            return HttpResponse(status=400)

        if not chargily_client.validate_signature(signature, payload):
            logger.warning('Chargily webhook: invalid signature')
            return HttpResponse(status=403)

        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            return HttpResponse(status=400)

        checkout_id = event.get('data', {}).get('id')
        event_type = event.get('type', '')

        if not checkout_id:
            logger.warning('Chargily webhook: missing checkout id')
            return HttpResponse(status=400)

        try:
            order = Order.objects.get(chargily_checkout_id=checkout_id)
        except Order.DoesNotExist:
            logger.warning(f'Chargily webhook: no order for checkout {checkout_id}')
            return HttpResponse(status=404)

        if event_type == 'checkout.paid':
            order.status = OrderStatus.PAID
            order.paymentRef = event.get('id', '')
            order.save(update_fields=['status', 'paymentRef', 'updated_at'])

            _auto_enroll_order_user(order)

            logger.info(f'Chargily webhook: order {order.id} marked as PAID')

        elif event_type == 'checkout.failed':
            order.status = OrderStatus.FAILED
            order.save(update_fields=['status', 'updated_at'])
            logger.info(f'Chargily webhook: order {order.id} marked as FAILED')

        elif event_type in ('checkout.canceled', 'checkout.expired'):
            order.status = OrderStatus.FAILED
            order.save(update_fields=['status', 'updated_at'])
            logger.info(f'Chargily webhook: order {order.id} — {event_type}')

        else:
            logger.warning(f'Chargily webhook: unknown event type {event_type}')
            return HttpResponse(status=400)

        return JsonResponse({}, status=200)


# ─── Promo Code ────────────────────────────────────────────────────────────────

class PromoCodeViewSet(viewsets.ModelViewSet):
    """
    Admin CRUD for promo codes + public validate action.

    Admin: GET/POST/PUT/DELETE /promo-codes/
    Public: POST /promo-codes/validate/
    """
    queryset = PromoCode.objects.all()
    serializer_class = PromoCodeSerializer
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        if self.action == 'validate':
            return [IsAuthenticated()]
        return [IsAdminOrReadOnly()]

    @action(detail=False, methods=['post'])
    def validate(self, request):
        """Validate a promo code for a specific course."""
        ser = PromoCodeValidateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        code_str = ser.validated_data['code'].strip().upper()
        course_id = ser.validated_data['course_id']

        try:
            promo = PromoCode.objects.get(code__iexact=code_str)
        except PromoCode.DoesNotExist:
            return Response({'valid': False, 'message': 'Code promo invalide.'}, status=400)

        if not promo.is_valid:
            return Response({'valid': False, 'message': 'Ce code promo a expiré ou est épuisé.'}, status=400)

        # Check per-user limit
        user_usage = PromoCodeUsage.objects.filter(user=request.user, promo_code=promo).count()
        if user_usage >= promo.max_uses_per_user:
            return Response({'valid': False, 'message': 'Vous avez déjà utilisé ce code.'}, status=400)

        # Check course restriction
        if promo.courses.exists() and not promo.courses.filter(id=course_id).exists():
            return Response({'valid': False, 'message': 'Ce code ne s\'applique pas à ce cours.'}, status=400)

        # Get course price
        try:
            course = Course.objects.get(id=course_id)
        except Course.DoesNotExist:
            return Response({'valid': False, 'message': 'Cours introuvable.'}, status=404)

        original_price = course.price if hasattr(course, 'price') else 0
        if promo.min_order_total and original_price < promo.min_order_total:
            return Response({
                'valid': False,
                'message': f'Le montant minimum est de {promo.min_order_total} DZD.',
            }, status=400)

        discount_amount = promo.compute_discount(original_price)
        final_price = max(0, original_price - discount_amount)

        return Response({
            'valid': True,
            'code': promo.code,
            'discount_type': promo.discount_type,
            'discount_value': str(promo.discount_value),
            'discount_amount': discount_amount,
            'final_price': final_price,
            'message': f'Code appliqué ! Réduction de {discount_amount} DZD.',
        })


# ─── Course Gift ───────────────────────────────────────────────────────────────

class CourseGiftViewSet(viewsets.GenericViewSet):
    """
    Gift a course to someone or claim a gift.

    POST /gifts/send/      — Purchase and send a gift
    POST /gifts/claim/     — Claim a gift by code
    GET  /gifts/my-sent/   — List gifts sent by current user
    GET  /gifts/my-received/ — List gifts received by current user
    """
    serializer_class = CourseGiftSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['post'])
    def send(self, request):
        """Send a course as a gift."""
        ser = CourseGiftSendSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        course_id = ser.validated_data['course_id']
        recipient_email = ser.validated_data['recipient_email']
        message = ser.validated_data.get('message', '')

        try:
            course = Course.objects.get(id=course_id)
        except Course.DoesNotExist:
            return Response({'detail': 'Cours introuvable.'}, status=404)

        # Don't gift to yourself
        if recipient_email == request.user.email:
            return Response({'detail': 'Vous ne pouvez pas vous offrir un cours.'}, status=400)

        # Sender must own (be enrolled in) the course
        if not Enrollment.objects.filter(user=request.user, course=course).exists():
            return Response({'detail': 'Vous devez être inscrit à ce cours pour l\'offrir.'}, status=400)

        # Check if recipient is already enrolled
        from django.contrib.auth import get_user_model
        user_model = get_user_model()
        recipient_user = user_model.objects.filter(email=recipient_email).first()
        if recipient_user and Enrollment.objects.filter(user=recipient_user, course=course).exists():
            return Response({'detail': 'Ce destinataire est déjà inscrit à ce cours.'}, status=400)

        # Create gift order (no new charge — sender already paid)
        order = Order.objects.create(
            user=request.user,
            total=0,  # No charge — it's a gift from an owned course
            status=OrderStatus.PAID,
            paymentMethod=PaymentMethod.FREE,
        )
        OrderItem.objects.create(order=order, course=course, price=0)

        # Create the gift
        from django.utils import timezone
        import datetime
        gift = CourseGift.objects.create(
            sender=request.user,
            recipient_email=recipient_email,
            course=course,
            order=order,
            message=message,
            expires_at=timezone.now() + datetime.timedelta(days=90),
        )

        # Send email notification to recipient (non-blocking)
        import threading
        from formation.services.gift_email import send_gift_email
        sender_name = (
            getattr(request.user, 'full_name', None)
            or getattr(request.user, 'display_name', None)
            or request.user.email
        )
        threading.Thread(
            target=send_gift_email,
            args=(recipient_email, sender_name, course.title, gift.gift_code, message),
            daemon=True,
        ).start()

        return Response({
            'gift_code': gift.gift_code,
            'recipient_email': gift.recipient_email,
            'course_title': course.title,
            'message': f'Cadeau envoyé ! Code: {gift.gift_code}',
        }, status=201)

    @action(detail=False, methods=['post'])
    def claim(self, request):
        """Claim a gift by code — auto-enrolls the user."""
        ser = CourseGiftClaimSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        gift_code = ser.validated_data['gift_code'].strip().upper()

        try:
            gift = CourseGift.objects.get(gift_code__iexact=gift_code)
        except CourseGift.DoesNotExist:
            return Response({'detail': 'Code cadeau invalide.'}, status=400)

        if not gift.is_valid:
            return Response({'detail': 'Ce cadeau a déjà été réclamé ou a expiré.'}, status=400)

        # Check if user is already enrolled
        if Enrollment.objects.filter(user=request.user, course=gift.course).exists():
            return Response({'detail': 'Vous êtes déjà inscrit à ce cours.'}, status=400)

        # Enroll the user
        from django.utils import timezone
        Enrollment.objects.create(user=request.user, course=gift.course)
        gift.recipient_user = request.user
        gift.status = GiftStatus.CLAIMED
        gift.claimed_at = timezone.now()
        gift.save(update_fields=['recipient_user', 'status', 'claimed_at'])

        return Response({
            'detail': 'Cadeau réclamé ! Vous êtes maintenant inscrit.',
            'course_id': str(gift.course.id),
            'course_slug': gift.course.slug,
        })

    @action(detail=False, methods=['get'], url_path='my-sent')
    def my_sent(self, request):
        """List gifts sent by the current user."""
        gifts = CourseGift.objects.filter(sender=request.user)
        return Response(CourseGiftSerializer(gifts, many=True).data)

    @action(detail=False, methods=['get'], url_path='my-received')
    def my_received(self, request):
        """List gifts received by the current user."""
        gifts = CourseGift.objects.filter(
            db_models.Q(recipient_user=request.user) |
            db_models.Q(recipient_email=request.user.email)
        )
        return Response(CourseGiftSerializer(gifts, many=True).data)
