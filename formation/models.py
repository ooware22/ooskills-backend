"""
Formation Module Models for OOSkills Platform

Covers: Courses, Sections, Lessons, Quizzes, Enrollments,
        Progress, Notes, Orders, Certificates, Sharing.

Category.name uses JSON i18n. All course-level fields are single-language
(determined by Course.language).
"""

import uuid
import secrets
from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from formation.storage import SupabaseAudioStorage, audio_upload_path
from formation.storage import SupabaseImageStorage, course_image_upload_path
from content.models import (
    TranslatableFieldMixin,
    validate_translation_json,
    SUPPORTED_LANGUAGES,
    DEFAULT_LANGUAGE,
    FALLBACK_ORDER,
)


# =============================================================================
# CATEGORY
# =============================================================================

class Category(models.Model, TranslatableFieldMixin):
    """Course category (Catégorie) — fully translatable."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.JSONField(
        'Nom',
        default=dict,
        validators=[validate_translation_json],
        help_text='{"fr": "...", "en": "...", "ar": "..."}'
    )
    slug = models.SlugField(max_length=140, unique=True, db_index=True)
    icon = models.CharField('Icône', max_length=60, blank=True,
                            help_text='Heroicon name or emoji')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Catégorie'
        verbose_name_plural = 'Catégories'
        ordering = ['slug']

    def __str__(self):
        return self.get_translated_value(self.name, 'fr')


# =============================================================================
# COURSE
# =============================================================================

class CourseLevel(models.TextChoices):
    BEGINNER = 'beginner', 'Débutant'
    INTERMEDIATE = 'intermediate', 'Intermédiaire'
    ADVANCED = 'advanced', 'Avancé'


class CourseStatus(models.TextChoices):
    DRAFT = 'draft', 'Brouillon'
    PUBLISHED = 'published', 'Publié'
    ARCHIVED = 'archived', 'Archivé'


class Course(models.Model):
    """
    Main course entity (Formation).

    Each course is in a single language (set by the ``language`` field).
    All text fields are in that one language.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    title = models.CharField('Titre', max_length=300)
    slug = models.SlugField(max_length=320, unique=True, db_index=True)
    description = models.TextField('Description', blank=True)
    prerequisites = models.JSONField(
        'Prérequis',
        default=list, blank=True,
        help_text='["item1", "item2", ...] — simple array of strings',
    )
    whatYouLearn = models.JSONField(
        'Ce que vous apprendrez',
        default=list, blank=True,
        help_text='["item1", "item2", ...] — simple array of strings',
    )

    # --- Non-translatable fields ---
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name='courses',
        null=True, blank=True,
    )
    level = models.CharField(
        max_length=20, choices=CourseLevel.choices,
        default=CourseLevel.BEGINNER,
    )
    duration = models.PositiveIntegerField(
        'Durée (heures)', default=0,
        help_text='Total course duration in hours',
    )
    rating = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    reviews = models.PositiveIntegerField(default=0)
    students = models.PositiveIntegerField(default=0)
    image = models.ImageField(
        'Image',
        upload_to=course_image_upload_path,
        storage=SupabaseImageStorage(),
        blank=True,
        help_text='Course thumbnail — uploaded to Supabase images/ bucket',
    )
    date = models.DateField('Date de publication', null=True, blank=True)
    price = models.PositiveIntegerField('Prix (DZD)', default=0)
    originalPrice = models.PositiveIntegerField('Prix original', default=0)
    language = models.CharField(max_length=60, default='English')
    certificate = models.BooleanField('Certificat inclus', default=True)
    lastUpdated = models.DateField('Dernière MàJ', null=True, blank=True)

    # --- Internal fields ---
    status = models.CharField(
        max_length=20, choices=CourseStatus.choices,
        default=CourseStatus.DRAFT, db_index=True,
    )
    instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='courses_created',
    )
    audioBasePath = models.CharField(
        max_length=500, blank=True,
        help_text='Base URL for audio files in Supabase Storage',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Formation'
        verbose_name_plural = 'Formations'
        ordering = ['-date', '-created_at']
        indexes = [
            models.Index(fields=['status', 'level']),
            models.Index(fields=['category', 'status']),
        ]

    def __str__(self):
        return self.title or '(untitled)'

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title) or str(self.id)[:8]
        super().save(*args, **kwargs)


# =============================================================================
# SECTION  (maps to TS CourseModule / frontend "modules" array)
# =============================================================================

class SectionType(models.TextChoices):
    TEASER = 'teaser', 'Teaser'
    INTRODUCTION = 'introduction', 'Introduction'
    MODULE = 'module', 'Module'
    CONCLUSION = 'conclusion', 'Conclusion'


class Section(models.Model):
    """A section inside a course."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name='sections',
    )
    title = models.CharField('Titre', max_length=300)
    type = models.CharField(
        max_length=20, choices=SectionType.choices,
        default=SectionType.MODULE,
    )
    sequence = models.PositiveIntegerField(
        default=0,
        help_text='Ordering weight inside the course',
    )
    audioFileIndex = models.PositiveIntegerField(
        default=0,
        help_text='Starting index in the audio files array',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Section'
        verbose_name_plural = 'Sections'
        ordering = ['sequence']
        unique_together = [['course', 'sequence']]

    def __str__(self):
        return f'{self.course.title} — {self.title}'

    # Computed properties used by serializer
    @property
    def lessons_count(self):
        return self.lessons.count()

    @property
    def total_duration(self):
        """Human-readable duration string based on child lessons."""
        total_seconds = self.lessons.aggregate(
            total=models.Sum('duration_seconds')
        )['total'] or 0
        hours = total_seconds / 3600
        if hours >= 1:
            return f'{hours:.1f}h'.replace('.0h', 'h')
        minutes = total_seconds / 60
        return f'{minutes:.0f}min'


# =============================================================================
# LESSON
# =============================================================================

class LessonType(models.TextChoices):
    SLIDE = 'slide', 'Diaporama'
    VIDEO = 'video', 'Vidéo'
    TEXT = 'text', 'Texte'
    AUDIO = 'audio', 'Audio'


class Lesson(models.Model):
    """A single lesson inside a section."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    section = models.ForeignKey(
        Section, on_delete=models.CASCADE, related_name='lessons',
    )
    title = models.CharField('Titre', max_length=300)
    type = models.CharField(
        max_length=20, choices=LessonType.choices,
        default=LessonType.SLIDE,
    )
    sequence = models.PositiveIntegerField(default=0)
    duration_seconds = models.PositiveIntegerField(
        'Durée (secondes)', default=0,
    )
    audioUrl = models.FileField(
        'Fichier audio',
        upload_to=audio_upload_path,
        storage=SupabaseAudioStorage(),
        blank=True,
        help_text='Audio file — uploaded to Supabase audios/<course_id>/',
    )
    content = models.JSONField(
        'Contenu (JSON)', default=dict, blank=True,
        help_text='Lesson content as a JSON object',
    )
    slide_type = models.CharField(max_length=60, blank=True,
                                  help_text='e.g. bullet_points, pillars, …')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Leçon'
        verbose_name_plural = 'Leçons'
        ordering = ['sequence']
        unique_together = [['section', 'sequence']]

    def __str__(self):
        return self.title or '(untitled)'


# =============================================================================
# QUIZ & QUESTIONS
# =============================================================================

class Quiz(models.Model):
    """Quiz attached to a section."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    section = models.OneToOneField(
        Section, on_delete=models.CASCADE, related_name='quiz',
    )
    title = models.CharField('Titre', max_length=300)
    intro_text = models.TextField('Texte d\'introduction', blank=True)
    pass_threshold = models.PositiveIntegerField(
        default=70, help_text='Percentage required to pass (0-100)',
    )
    max_attempts = models.PositiveIntegerField(
        default=3, help_text='0 = unlimited',
    )
    xp_reward = models.PositiveIntegerField(
        default=10, help_text='XP points awarded on pass',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Quiz'
        verbose_name_plural = 'Quiz'

    def __str__(self):
        return self.title or '(untitled)'


class QuestionType(models.TextChoices):
    MULTIPLE_CHOICE = 'multiple_choice', 'QCM'
    TRUE_FALSE = 'true_false', 'Vrai/Faux'
    SCENARIO = 'scenario', 'Scénario'


class QuestionDifficulty(models.TextChoices):
    EASY = 'easy', 'Facile'
    MEDIUM = 'medium', 'Moyen'
    HARD = 'hard', 'Difficile'


class QuizQuestion(models.Model):
    """
    A single quiz question.

    ``options`` is a simple array: ["A", "B", "C"]
    ``correct_answer`` is the 0-based index of the correct option.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    quiz = models.ForeignKey(
        Quiz, on_delete=models.CASCADE, related_name='questions',
    )
    type = models.CharField(
        max_length=30, choices=QuestionType.choices,
        default=QuestionType.MULTIPLE_CHOICE,
    )
    question = models.TextField('Question')
    options = models.JSONField(
        'Options',
        default=list,
        help_text='["Option A", "Option B", "Option C"]',
    )
    correct_answer = models.PositiveIntegerField(
        help_text='0-based index of the correct option',
    )
    explanation = models.TextField('Explication', blank=True)
    difficulty = models.CharField(
        max_length=20, choices=QuestionDifficulty.choices,
        default=QuestionDifficulty.EASY,
    )
    category = models.CharField(max_length=60, blank=True,
                                help_text='e.g. general, memorisation, raisonnement')
    sequence = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Question'
        verbose_name_plural = 'Questions'
        ordering = ['sequence']

    def __str__(self):
        return (self.question or '(empty)')[:80]


# =============================================================================
# FINAL QUIZ (course-level exam for certificate)
# =============================================================================

class FinalQuiz(models.Model):
    """Course-level final exam — random questions from all section quizzes."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    course = models.OneToOneField(
        Course, on_delete=models.CASCADE, related_name='final_quiz',
    )
    title = models.CharField('Titre', max_length=300, default='Examen Final')
    num_questions = models.PositiveIntegerField(
        default=20, help_text='Number of random questions to pull from section quizzes',
    )
    pass_threshold = models.PositiveIntegerField(
        default=70, help_text='Percentage required to pass (0-100)',
    )
    max_attempts = models.PositiveIntegerField(
        default=3, help_text='0 = unlimited',
    )
    xp_reward = models.PositiveIntegerField(
        default=50, help_text='XP points awarded on pass',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Examen Final'
        verbose_name_plural = 'Examens Finaux'

    def __str__(self):
        return f'Final Quiz — {self.course.title}'


# =============================================================================
# ENROLLMENT
# =============================================================================

class EnrollmentStatus(models.TextChoices):
    ACTIVE = 'active', 'Actif'
    COMPLETED = 'completed', 'Terminé'
    CANCELLED = 'cancelled', 'Annulé'
    EXPIRED = 'expired', 'Expiré'


class Enrollment(models.Model):
    """User enrolment in a course (Inscription)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='enrollments',
    )
    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name='enrollments',
    )
    progress = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text='Overall completion percentage 0-100',
    )
    status = models.CharField(
        max_length=20, choices=EnrollmentStatus.choices,
        default=EnrollmentStatus.ACTIVE,
    )
    enrolled_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Inscription'
        verbose_name_plural = 'Inscriptions'
        unique_together = [['user', 'course']]
        ordering = ['-enrolled_at']
        indexes = [
            models.Index(fields=['user', 'status']),
        ]

    def __str__(self):
        return f'{self.user} — {self.course}'


# =============================================================================
# LESSON PROGRESS (per user per lesson)
# =============================================================================

class LessonProgress(models.Model):
    """Tracks the student's progress inside a single lesson."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    enrollment = models.ForeignKey(
        Enrollment, on_delete=models.CASCADE, related_name='lesson_progress',
    )
    lesson = models.ForeignKey(
        Lesson, on_delete=models.CASCADE, related_name='progress_records',
    )
    current_slide = models.PositiveIntegerField(default=0)
    completed = models.BooleanField(default=False)
    last_position = models.PositiveIntegerField(
        default=0, help_text='Audio position in seconds',
    )
    time_spent = models.PositiveIntegerField(
        default=0, help_text='Total time spent in seconds',
    )
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Progression leçon'
        verbose_name_plural = 'Progressions leçons'
        unique_together = [['enrollment', 'lesson']]

    def __str__(self):
        status = '✓' if self.completed else f'{self.current_slide}'
        return f'{self.enrollment.user} — {self.lesson} [{status}]'


# =============================================================================
# LESSON NOTES
# =============================================================================

class LessonNote(models.Model):
    """User note attached to a specific slide in a lesson."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    enrollment = models.ForeignKey(
        Enrollment, on_delete=models.CASCADE, related_name='notes',
    )
    lesson = models.ForeignKey(
        Lesson, on_delete=models.CASCADE, related_name='notes',
    )
    content = models.TextField()
    slide_index = models.PositiveIntegerField(
        default=0, help_text='Slide index the note is attached to',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Note'
        verbose_name_plural = 'Notes'
        ordering = ['slide_index', 'created_at']

    def __str__(self):
        return f'Note by {self.enrollment.user} on {self.lesson}'


# =============================================================================
# QUIZ ATTEMPT
# =============================================================================

class QuizAttempt(models.Model):
    """A single attempt at a quiz by a student."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    enrollment = models.ForeignKey(
        Enrollment, on_delete=models.CASCADE, related_name='quiz_attempts',
    )
    quiz = models.ForeignKey(
        Quiz, on_delete=models.CASCADE, related_name='attempts',
    )
    score = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text='Score percentage 0-100',
    )
    answers = models.JSONField(
        default=dict, help_text='Map of question_id -> selected_option_index',
    )
    passed = models.BooleanField(default=False)
    xp_earned = models.PositiveIntegerField(default=0)
    feedback = models.JSONField(
        default=list, blank=True,
        help_text='Per-question feedback returned to frontend',
    )
    attempt_number = models.PositiveIntegerField(default=1)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Tentative de quiz'
        verbose_name_plural = 'Tentatives de quiz'
        ordering = ['-submitted_at']

    def __str__(self):
        return f'{self.enrollment.user} — {self.quiz} (#{self.attempt_number})'


# =============================================================================
# FINAL QUIZ ATTEMPT
# =============================================================================

class FinalQuizAttempt(models.Model):
    """A single attempt at the course-level final quiz."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    enrollment = models.ForeignKey(
        Enrollment, on_delete=models.CASCADE, related_name='final_quiz_attempts',
    )
    final_quiz = models.ForeignKey(
        FinalQuiz, on_delete=models.CASCADE, related_name='attempts',
    )
    score = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text='Score percentage 0-100',
    )
    answers = models.JSONField(
        default=dict, help_text='Map of question_id -> selected_option_index',
    )
    questions_snapshot = models.JSONField(
        default=list,
        help_text='Snapshot of random question IDs selected for this attempt',
    )
    passed = models.BooleanField(default=False)
    xp_earned = models.PositiveIntegerField(default=0)
    feedback = models.JSONField(
        default=list, blank=True,
        help_text='Per-question feedback returned to frontend',
    )
    attempt_number = models.PositiveIntegerField(default=1)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Tentative examen final'
        verbose_name_plural = 'Tentatives examen final'
        ordering = ['-submitted_at']

    def __str__(self):
        return f'{self.enrollment.user} — Final Quiz (#{self.attempt_number})'


# =============================================================================
# ORDER & ORDER ITEMS
# =============================================================================

class OrderStatus(models.TextChoices):
    PENDING = 'pending', 'En attente'
    PAID = 'paid', 'Payé'
    FAILED = 'failed', 'Échoué'
    REFUNDED = 'refunded', 'Remboursé'


class PaymentMethod(models.TextChoices):
    CCP = 'ccp', 'CCP'
    BARIDIMOB = 'baridimob', 'BaridiMob'
    CARD = 'card', 'Carte bancaire'
    EDAHABIA = 'edahabia', 'Edahabia'
    FREE = 'free', 'Gratuit'


class Order(models.Model):
    """Payment order (Commande)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='orders',
    )
    total = models.PositiveIntegerField('Total (DZD)', default=0)
    status = models.CharField(
        max_length=20, choices=OrderStatus.choices,
        default=OrderStatus.PENDING,
    )
    paymentMethod = models.CharField(
        max_length=30, choices=PaymentMethod.choices,
        default=PaymentMethod.CCP,
    )
    paymentRef = models.CharField(
        'Référence de paiement', max_length=200, blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Commande'
        verbose_name_plural = 'Commandes'
        ordering = ['-created_at']

    def __str__(self):
        return f'Order {self.id} — {self.user}'


class OrderItem(models.Model):
    """Line item inside an order."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name='items',
    )
    course = models.ForeignKey(
        Course, on_delete=models.PROTECT, related_name='order_items',
    )
    price = models.PositiveIntegerField('Prix unitaire (DZD)', default=0)

    class Meta:
        verbose_name = 'Article'
        verbose_name_plural = 'Articles'

    def __str__(self):
        return f'{self.course} @ {self.price} DZD'


# =============================================================================
# CERTIFICATE
# =============================================================================

class Certificate(models.Model):
    """Certificate issued upon passing the final quiz (Certificat)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='certificates',
    )
    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name='certificates',
    )
    score = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text='Final quiz score achieved',
    )
    code = models.CharField(
        max_length=40, unique=True, db_index=True,
        help_text='Unique verification code',
    )
    pdf_url = models.URLField(
        'PDF URL', max_length=500, blank=True,
        help_text='URL to the generated PDF certificate in Supabase',
    )
    issuedAt = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = 'Certificat'
        verbose_name_plural = 'Certificats'
        unique_together = [['user', 'course']]
        ordering = ['-issuedAt']

    def __str__(self):
        return f'Certificate {self.code} — {self.user}'

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = f'OOS-{secrets.token_hex(6).upper()}'
        super().save(*args, **kwargs)


# =============================================================================
# SHARE TOKEN (sharing / referral access)
# =============================================================================

class ShareVisibility(models.TextChoices):
    PUBLIC = 'public', 'Public'
    PRIVATE = 'private', 'Privé'
    TOKEN = 'token', 'Par lien'


class ShareToken(models.Model):
    """
    Token-based sharing for courses.

    Supports public, private, and referral-link access models.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name='share_tokens',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='share_tokens',
    )
    token = models.CharField(
        max_length=64, unique=True, db_index=True,
    )
    visibility = models.CharField(
        max_length=20, choices=ShareVisibility.choices,
        default=ShareVisibility.TOKEN,
    )
    max_uses = models.PositiveIntegerField(
        default=0, help_text='0 = unlimited',
    )
    uses_count = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Lien de partage'
        verbose_name_plural = 'Liens de partage'

    def __str__(self):
        return f'Share {self.token[:8]}… for {self.course}'

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_urlsafe(32)
        super().save(*args, **kwargs)

    @property
    def is_valid(self):
        if not self.is_active:
            return False
        if self.max_uses and self.uses_count >= self.max_uses:
            return False
        if self.expires_at and timezone.now() > self.expires_at:
            return False
        return True
