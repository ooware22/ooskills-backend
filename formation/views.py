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
    Category, Certificate, Course, CourseRating, CourseStatus, Enrollment,
    FinalQuiz, FinalQuizAttempt,
    Lesson, LessonNote, LessonProgress, Order, OrderItem, OrderStatus,
    QuizAttempt, Quiz, QuizQuestion, Section, ShareToken,
)
from formation.serializers import (
    CategorySerializer, CertificateSerializer,
    CourseDetailSerializer, CourseListSerializer, CourseWriteSerializer,
    CourseRatingSerializer, CourseRatingCreateSerializer,
    EnrollmentCreateSerializer, EnrollmentSerializer,
    FinalQuizSerializer, FinalQuizGenerateSerializer,
    FinalQuizSubmitSerializer, FinalQuizAttemptSerializer,
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
from formation.services.final_quiz_service import (
    generate_final_quiz_questions, submit_final_quiz,
    FinalQuizNotConfigured, FinalQuizLimitExceeded, CourseNotCompleted as FQCourseNotCompleted,
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
            if not user.is_authenticated:
                return qs.none()
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

        # Free order → mark paid immediately
        if total == 0:
            order.status = OrderStatus.PAID
            order.save(update_fields=['status'])

        # Auto-enroll the user in each course (skip if already enrolled)
        for course in courses:
            try:
                enroll_user(request.user, course)
            except AlreadyEnrolled:
                pass

        return Response(
            OrderSerializer(order).data,
            status=status.HTTP_201_CREATED,
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
                {'detail': 'Not enrolled in this course.'},
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
                {'detail': 'Not enrolled in this course.'},
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
