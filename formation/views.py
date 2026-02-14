"""
Formation Views — DRF ViewSets for all formation endpoints.
"""

from rest_framework import viewsets, status, mixins
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter
from drf_spectacular.utils import extend_schema, extend_schema_view

from formation.models import (
    Category, Certificate, Course, CourseStatus, Enrollment,
    Lesson, LessonNote, LessonProgress, Order, OrderItem,
    QuizAttempt, Quiz, QuizQuestion, Section, ShareToken,
)
from formation.serializers import (
    CategorySerializer, CertificateSerializer,
    CourseDetailSerializer, CourseListSerializer, CourseWriteSerializer,
    EnrollmentCreateSerializer, EnrollmentSerializer,
    LessonNoteSerializer, LessonProgressSerializer, LessonSerializer,
    OrderCreateSerializer, OrderSerializer,
    ProgressAutosaveSerializer,
    QuizAttemptSerializer, QuizSerializer, QuizSubmitSerializer,
    QuizQuestionSerializer,
    SectionDetailSerializer, SectionSerializer,
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
class CourseViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdminOrReadOnly]
    lookup_field = 'slug'
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = CourseFilter
    ordering_fields = ['date', 'price', 'rating', 'students', 'created_at']
    ordering = ['-date']

    def get_queryset(self):
        qs = Course.objects.select_related('category').prefetch_related(
            'sections__lessons',
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


@extend_schema_view(
    list=extend_schema(summary='List sections (optionally filter by course slug)'),
    retrieve=extend_schema(summary='Retrieve a section with lessons'),
)
class SectionViewSet(viewsets.ModelViewSet):
    """
    Sections API.

    List: GET /api/formation/sections/?course=<course-slug>
    Detail: GET /api/formation/sections/<id>/
    """
    permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        qs = Section.objects.select_related('course').prefetch_related(
            'lessons', 'quiz__questions',
        )
        course_slug = self.request.query_params.get('course')
        if course_slug:
            qs = qs.filter(course__slug=course_slug)
        return qs

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return SectionDetailSerializer
        return SectionDetailSerializer


# ─── Lesson ──────────────────────────────────────────────────────────────────

class LessonViewSet(viewsets.ModelViewSet):
    """
    Lesson CRUD. Audio uploads via the audioUrl FileField go
    directly to Supabase Storage (audios/<course_id>/).
    """
    serializer_class = LessonSerializer
    permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        user = self.request.user
        qs = Lesson.objects.select_related('section__course')
        if not (user.is_authenticated and user.is_admin):
            enrolled_courses = Enrollment.objects.filter(
                user=user
            ).values_list('course_id', flat=True)
            qs = qs.filter(section__course_id__in=enrolled_courses)
        return qs

# ─── Quiz ────────────────────────────────────────────────────────────────────

class QuizViewSet(viewsets.ModelViewSet):
    """
    Quiz CRUD.

    Filter by section: GET /api/formation/quizzes/?section=<section-id>
    """
    serializer_class = QuizSerializer
    permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        qs = Quiz.objects.prefetch_related('questions')
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
        user = self.request.user
        if user.is_admin:
            return Enrollment.objects.all().select_related('course')
        return Enrollment.objects.filter(user=user).select_related('course')

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
                {'detail': 'Course not found.'},
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
            lesson = Lesson.objects.select_related('section__course').get(id=lesson_id)
        except Lesson.DoesNotExist:
            return Response(
                {'detail': 'Lesson not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            enrollment = Enrollment.objects.get(
                user=request.user, course=lesson.section.course,
            )
        except Enrollment.DoesNotExist:
            return Response(
                {'detail': 'Not enrolled in this course.'},
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
            course=lesson.section.course,
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
                {'detail': 'Not enrolled in this course.'},
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

        return Response(
            OrderSerializer(order).data,
            status=status.HTTP_201_CREATED,
        )


# ─── Certificate ─────────────────────────────────────────────────────────────

@extend_schema_view(
    list=extend_schema(summary='List my certificates'),
    retrieve=extend_schema(summary='Retrieve a certificate'),
)
class CertificateViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CertificateSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrAdmin]

    def get_queryset(self):
        user = self.request.user
        if user.is_admin:
            return Certificate.objects.all().select_related('course', 'user')
        return Certificate.objects.filter(user=user).select_related('course', 'user')

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
                {'detail': 'Course not found.'},
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
