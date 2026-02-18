"""
Formation Serializers — aligned with frontend TS contracts.

All translatable fields are returned as JSON objects:
{"fr": "...", "en": "...", "ar": "..."}

The frontend picks the right language based on user preference.
"""

from rest_framework import serializers

from formation.models import (
    Category, Certificate, Course, CourseRating, Enrollment,
    FinalQuiz, FinalQuizAttempt,
    Lesson, LessonNote, LessonProgress, Order, OrderItem,
    QuizAttempt, Quiz, QuizQuestion, Section, ShareToken,
)


# ─── Category ────────────────────────────────────────────────────────────────

class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'icon']


# ─── Quiz & Questions ────────────────────────────────────────────────────────

class QuizQuestionSerializer(serializers.ModelSerializer):
    """Matches TS ``QuizQuestion`` interface — all text fields are i18n JSON."""

    class Meta:
        model = QuizQuestion
        fields = [
            'id', 'quiz', 'type', 'question', 'options',
            'correct_answer', 'explanation', 'difficulty', 'category', 'sequence',
        ]


class QuizSerializer(serializers.ModelSerializer):
    questions = QuizQuestionSerializer(many=True, read_only=True)

    class Meta:
        model = Quiz
        fields = [
            'id', 'section', 'title', 'intro_text', 'questions',
            'pass_threshold', 'max_attempts', 'xp_reward',
        ]


# ─── Lesson ──────────────────────────────────────────────────────────────────

class LessonSerializer(serializers.ModelSerializer):
    """Full lesson with slide content — title, audioUrl, content are i18n JSON."""

    class Meta:
        model = Lesson
        fields = [
            'id', 'section', 'title', 'type', 'sequence',
            'duration_seconds', 'audioUrl', 'content', 'slide_type',
        ]

    def to_internal_value(self, data):
        """Parse JSON string fields that arrive via multipart/form-data."""
        import json
        if hasattr(data, 'getlist'):  # QueryDict from multipart
            # Build a plain mutable dict instead of deep-copying QueryDict
            # (deep copy fails on uploaded file objects)
            mutable = {}
            for key in data:
                mutable[key] = data[key]
            content_raw = mutable.get('content')
            if isinstance(content_raw, str):
                try:
                    mutable['content'] = json.loads(content_raw)
                except (json.JSONDecodeError, TypeError):
                    pass
            return super().to_internal_value(mutable)
        return super().to_internal_value(data)


class LessonListSerializer(serializers.ModelSerializer):
    """Lightweight: no content blob, for section listings."""

    class Meta:
        model = Lesson
        fields = ['id', 'section', 'title', 'type', 'sequence', 'duration_seconds', 'slide_type']


# ─── Section ─────────────────────────────────────────────────────────────────

class SectionSerializer(serializers.ModelSerializer):
    """
    Matches TS ``CourseModule`` for catalog view:
    { title (i18n), lessons (count), duration (string) }
    """
    lessons = serializers.IntegerField(source='lessons_count', read_only=True)
    duration = serializers.CharField(source='total_duration', read_only=True)

    class Meta:
        model = Section
        fields = ['id', 'course', 'title', 'type', 'sequence', 'lessons', 'duration']


class SectionDetailSerializer(serializers.ModelSerializer):
    """Section with nested lessons for course detail / player."""
    lessons_list = LessonSerializer(source='lessons', many=True, read_only=True)
    quiz = QuizSerializer(read_only=True)
    lessons = serializers.IntegerField(source='lessons_count', read_only=True)
    duration = serializers.CharField(source='total_duration', read_only=True)

    class Meta:
        model = Section
        fields = [
            'id', 'course', 'title', 'type', 'sequence', 'audioFileIndex',
            'lessons', 'duration', 'lessons_list', 'quiz',
        ]


# ─── Course ──────────────────────────────────────────────────────────────────

class CourseListSerializer(serializers.ModelSerializer):
    """
    Catalog listing matching TS ``Course`` interface.

    ``title``, ``description``, ``prerequisites``, ``whatYouLearn`` are i18n JSON.
    ``category`` is the slug string.
    ``modules`` is the computed sections summary.
    """
    category = serializers.SlugRelatedField(slug_field='slug', read_only=True)
    modules = SectionSerializer(source='sections', many=True, read_only=True)

    class Meta:
        model = Course
        fields = [
            'id', 'title', 'slug', 'category', 'level', 'duration',
            'rating', 'reviews', 'students', 'image', 'date',
            'price', 'originalPrice', 'description',
            'prerequisites', 'whatYouLearn', 'modules',
            'language', 'certificate', 'lastUpdated',
        ]


class CourseDetailSerializer(serializers.ModelSerializer):
    """Detailed course with full section/lesson/quiz data for the player."""
    category = serializers.SlugRelatedField(slug_field='slug', read_only=True)
    modules = SectionDetailSerializer(source='sections', many=True, read_only=True)
    totalModules = serializers.SerializerMethodField()
    totalSlides = serializers.SerializerMethodField()
    totalQuizQuestions = serializers.SerializerMethodField()

    class Meta:
        model = Course
        fields = [
            'id', 'title', 'slug', 'category', 'level', 'duration',
            'rating', 'reviews', 'students', 'image', 'date',
            'price', 'originalPrice', 'description',
            'prerequisites', 'whatYouLearn', 'modules',
            'language', 'certificate', 'lastUpdated',
            'audioBasePath', 'totalModules', 'totalSlides', 'totalQuizQuestions',
        ]

    def get_totalModules(self, obj):
        return obj.sections.count()

    def get_totalSlides(self, obj):
        return Lesson.objects.filter(section__course=obj).count()

    def get_totalQuizQuestions(self, obj):
        return QuizQuestion.objects.filter(quiz__section__course=obj).count()


class CourseWriteSerializer(serializers.ModelSerializer):
    """Admin write serializer for creating/updating courses."""
    category = serializers.SlugRelatedField(
        slug_field='slug', queryset=Category.objects.all(),
        required=False, allow_null=True,
    )

    class Meta:
        model = Course
        fields = [
            'title', 'slug', 'category', 'level', 'duration',
            'rating', 'reviews', 'students', 'image', 'date',
            'price', 'originalPrice', 'description',
            'prerequisites', 'whatYouLearn',
            'language', 'certificate', 'lastUpdated',
            'status', 'audioBasePath',
        ]


# ─── Enrollment ──────────────────────────────────────────────────────────────

class EnrollmentSerializer(serializers.ModelSerializer):
    course_title = serializers.CharField(source='course.title', read_only=True)
    course_slug = serializers.CharField(source='course.slug', read_only=True)
    course_image = serializers.SerializerMethodField()

    class Meta:
        model = Enrollment
        fields = [
            'id', 'user', 'course', 'progress', 'status',
            'enrolled_at', 'completed_at',
            'course_title', 'course_slug', 'course_image',
        ]
        read_only_fields = ['id', 'user', 'progress', 'status', 'enrolled_at', 'completed_at']

    def get_course_image(self, obj):
        if obj.course.image:
            return obj.course.image.url
        return None


class EnrollmentCreateSerializer(serializers.Serializer):
    courseId = serializers.UUIDField()


# ─── Lesson Progress ────────────────────────────────────────────────────────

class LessonProgressSerializer(serializers.ModelSerializer):
    class Meta:
        model = LessonProgress
        fields = [
            'id', 'enrollment', 'lesson',
            'current_slide', 'completed', 'last_position', 'time_spent',
            'started_at', 'completed_at', 'updated_at',
        ]
        read_only_fields = ['id', 'started_at', 'completed_at', 'updated_at']


class ProgressAutosaveSerializer(serializers.Serializer):
    """Input for the autosave endpoint."""
    lesson_id = serializers.UUIDField()
    current_slide = serializers.IntegerField(min_value=0, default=0)
    last_position = serializers.IntegerField(min_value=0, default=0)
    time_spent_delta = serializers.IntegerField(min_value=0, default=0)
    completed = serializers.BooleanField(default=False)


# ─── Lesson Notes ────────────────────────────────────────────────────────────

class LessonNoteSerializer(serializers.ModelSerializer):
    class Meta:
        model = LessonNote
        fields = [
            'id', 'enrollment', 'lesson',
            'content', 'slide_index',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'enrollment', 'created_at', 'updated_at']


# ─── Quiz Attempt ────────────────────────────────────────────────────────────

class QuizAttemptSerializer(serializers.ModelSerializer):
    remaining_attempts = serializers.SerializerMethodField()

    class Meta:
        model = QuizAttempt
        fields = [
            'id', 'enrollment', 'quiz',
            'score', 'answers', 'passed', 'xp_earned',
            'feedback', 'attempt_number', 'submitted_at',
            'remaining_attempts',
        ]
        read_only_fields = [
            'id', 'enrollment', 'score', 'passed',
            'xp_earned', 'feedback', 'attempt_number', 'submitted_at',
        ]

    def get_remaining_attempts(self, obj):
        from formation.services.quiz_service import get_remaining_attempts
        return get_remaining_attempts(obj.enrollment, obj.quiz)


class QuizSubmitSerializer(serializers.Serializer):
    """Input for quiz submission."""
    quiz_id = serializers.UUIDField()
    answers = serializers.DictField(
        child=serializers.IntegerField(),
        help_text='Map of question_id -> selected_option_index',
    )


# ─── Final Quiz ──────────────────────────────────────────────────────────────

class FinalQuizSerializer(serializers.ModelSerializer):
    """Read-only config for the course final quiz."""
    remaining_attempts = serializers.SerializerMethodField()
    has_passed = serializers.SerializerMethodField()

    class Meta:
        model = FinalQuiz
        fields = [
            'id', 'course', 'title', 'num_questions',
            'pass_threshold', 'max_attempts', 'xp_reward',
            'remaining_attempts', 'has_passed',
        ]

    def get_remaining_attempts(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        from formation.services.final_quiz_service import get_final_quiz_remaining_attempts
        try:
            enrollment = Enrollment.objects.get(
                user=request.user, course=obj.course,
            )
            return get_final_quiz_remaining_attempts(enrollment, obj)
        except Enrollment.DoesNotExist:
            return None

    def get_has_passed(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        return FinalQuizAttempt.objects.filter(
            enrollment__user=request.user,
            final_quiz=obj,
            passed=True,
        ).exists()


class FinalQuizGenerateSerializer(serializers.Serializer):
    """Input for generating final quiz questions."""
    course_id = serializers.UUIDField()


class FinalQuizSubmitSerializer(serializers.Serializer):
    """Input for submitting final quiz answers."""
    course_id = serializers.UUIDField()
    question_ids = serializers.ListField(
        child=serializers.UUIDField(),
        help_text='List of question IDs that were presented',
    )
    answers = serializers.DictField(
        child=serializers.IntegerField(),
        help_text='Map of question_id -> selected_option_index',
    )


class FinalQuizAttemptSerializer(serializers.ModelSerializer):
    """Output for final quiz attempt results."""
    remaining_attempts = serializers.SerializerMethodField()

    class Meta:
        model = FinalQuizAttempt
        fields = [
            'id', 'enrollment', 'final_quiz',
            'score', 'answers', 'questions_snapshot',
            'passed', 'xp_earned', 'feedback',
            'attempt_number', 'submitted_at',
            'remaining_attempts',
        ]
        read_only_fields = [
            'id', 'enrollment', 'score', 'passed',
            'xp_earned', 'feedback', 'attempt_number', 'submitted_at',
        ]

    def get_remaining_attempts(self, obj):
        from formation.services.final_quiz_service import get_final_quiz_remaining_attempts
        return get_final_quiz_remaining_attempts(obj.enrollment, obj.final_quiz)


# ─── Order ───────────────────────────────────────────────────────────────────

class OrderItemSerializer(serializers.ModelSerializer):
    course_title = serializers.CharField(source='course.title', read_only=True)

    class Meta:
        model = OrderItem
        fields = ['id', 'course', 'course_title', 'price']


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = [
            'id', 'user', 'total', 'status',
            'paymentMethod', 'paymentRef',
            'items', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'user', 'total', 'status', 'created_at', 'updated_at']


class OrderCreateSerializer(serializers.Serializer):
    """Input for creating an order."""
    course_ids = serializers.ListField(child=serializers.UUIDField())
    paymentMethod = serializers.CharField(max_length=30)
    paymentRef = serializers.CharField(max_length=200, required=False, default='')


# ─── Certificate ─────────────────────────────────────────────────────────────

class CertificateSerializer(serializers.ModelSerializer):
    course_title = serializers.CharField(source='course.title', read_only=True)
    user_name = serializers.CharField(source='user.full_name', read_only=True)

    class Meta:
        model = Certificate
        fields = [
            'id', 'user', 'course', 'score', 'code', 'pdf_url', 'issuedAt',
            'course_title', 'user_name',
        ]
        read_only_fields = ['id', 'user', 'course', 'score', 'code', 'pdf_url', 'issuedAt']


# ─── Share Token ─────────────────────────────────────────────────────────────

class ShareTokenSerializer(serializers.ModelSerializer):
    course_title = serializers.CharField(source='course.title', read_only=True)
    is_valid = serializers.BooleanField(read_only=True)

    class Meta:
        model = ShareToken
        fields = [
            'id', 'course', 'course_title', 'token',
            'visibility', 'max_uses', 'uses_count',
            'expires_at', 'is_active', 'is_valid',
            'created_at',
        ]
        read_only_fields = [
            'id', 'token', 'uses_count', 'is_valid', 'created_at',
        ]


class ShareTokenCreateSerializer(serializers.Serializer):
    """Input for creating a share token."""
    course_id = serializers.UUIDField()
    visibility = serializers.ChoiceField(
        choices=['public', 'private', 'token'], default='token',
    )
    max_uses = serializers.IntegerField(min_value=0, default=0)
    expires_in_days = serializers.IntegerField(
        min_value=0, required=False, allow_null=True,
    )


# ─── Course Rating ────────────────────────────────────────────────────────────

class CourseRatingSerializer(serializers.ModelSerializer):
    """Read-only serializer for displaying ratings."""
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = CourseRating
        fields = ['id', 'user', 'course', 'rating', 'review_text', 'user_name', 'created_at']
        read_only_fields = fields

    def get_user_name(self, obj):
        u = obj.user
        if u.first_name and u.last_name:
            return f'{u.first_name} {u.last_name}'
        return u.email.split('@')[0]


class CourseRatingCreateSerializer(serializers.Serializer):
    """Input serializer for submitting / updating a rating."""
    rating = serializers.IntegerField(min_value=1, max_value=5)
    review_text = serializers.CharField(required=False, allow_blank=True, default='')

