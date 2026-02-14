"""
Formation Admin — register all models with inlines for efficient editing.

All translatable fields are JSONFields ({"fr": ..., "en": ..., "ar": ...}).
"""

from django.contrib import admin
from formation.models import (
    Category, Certificate, Course, Enrollment,
    Lesson, LessonNote, LessonProgress, Order, OrderItem,
    QuizAttempt, Quiz, QuizQuestion, Section, ShareToken,
)


# ─── Inlines ─────────────────────────────────────────────────────────────────

class SectionInline(admin.TabularInline):
    model = Section
    extra = 0
    fields = ['title', 'type', 'sequence', 'audioFileIndex']
    ordering = ['sequence']


class LessonInline(admin.TabularInline):
    model = Lesson
    extra = 0
    fields = ['title', 'type', 'sequence', 'duration_seconds', 'slide_type']
    ordering = ['sequence']


class QuizQuestionInline(admin.TabularInline):
    model = QuizQuestion
    extra = 0
    fields = ['question', 'type', 'options', 'correct_answer', 'difficulty', 'sequence']
    ordering = ['sequence']


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    fields = ['course', 'price']
    raw_id_fields = ['course']


# ─── Model Admins ────────────────────────────────────────────────────────────

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['slug', 'icon']
    search_fields = ['slug']


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ['slug', 'category', 'level', 'price', 'status', 'students', 'rating', 'date']
    list_filter = ['status', 'level', 'category']
    search_fields = ['slug']
    raw_id_fields = ['instructor', 'category']
    inlines = [SectionInline]
    fieldsets = (
        (None, {
            'fields': ('title', 'slug', 'category', 'description', 'image')
        }),
        ('Détails', {
            'fields': ('level', 'duration', 'language', 'certificate', 'price', 'originalPrice')
        }),
        ('Stats', {
            'fields': ('rating', 'reviews', 'students')
        }),
        ('Dates & Statut', {
            'fields': ('date', 'lastUpdated', 'status', 'instructor', 'audioBasePath')
        }),
        ('Contenu JSON (i18n)', {
            'classes': ('collapse',),
            'fields': ('prerequisites', 'whatYouLearn')
        }),
    )


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = ['course', 'type', 'sequence']
    list_filter = ['type']
    raw_id_fields = ['course']
    inlines = [LessonInline]


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ['section', 'type', 'sequence', 'duration_seconds']
    list_filter = ['type']
    raw_id_fields = ['section']


@admin.register(Quiz)
class QuizAdmin(admin.ModelAdmin):
    list_display = ['section', 'pass_threshold', 'max_attempts', 'xp_reward']
    raw_id_fields = ['section']
    inlines = [QuizQuestionInline]


@admin.register(QuizQuestion)
class QuizQuestionAdmin(admin.ModelAdmin):
    list_display = ['quiz', 'type', 'difficulty', 'correct_answer']
    list_filter = ['type', 'difficulty']
    raw_id_fields = ['quiz']


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ['user', 'course', 'progress', 'status', 'enrolled_at']
    list_filter = ['status']
    raw_id_fields = ['user', 'course']
    search_fields = ['user__email']


@admin.register(LessonProgress)
class LessonProgressAdmin(admin.ModelAdmin):
    list_display = ['enrollment', 'lesson', 'current_slide', 'completed', 'time_spent']
    list_filter = ['completed']
    raw_id_fields = ['enrollment', 'lesson']


@admin.register(LessonNote)
class LessonNoteAdmin(admin.ModelAdmin):
    list_display = ['enrollment', 'lesson', 'slide_index', 'created_at']
    raw_id_fields = ['enrollment', 'lesson']


@admin.register(QuizAttempt)
class QuizAttemptAdmin(admin.ModelAdmin):
    list_display = ['enrollment', 'quiz', 'score', 'passed', 'xp_earned', 'attempt_number', 'submitted_at']
    list_filter = ['passed']
    raw_id_fields = ['enrollment', 'quiz']


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'total', 'status', 'paymentMethod', 'created_at']
    list_filter = ['status', 'paymentMethod']
    raw_id_fields = ['user']
    inlines = [OrderItemInline]


@admin.register(Certificate)
class CertificateAdmin(admin.ModelAdmin):
    list_display = ['code', 'user', 'course', 'score', 'issuedAt']
    search_fields = ['code', 'user__email']
    raw_id_fields = ['user', 'course']


@admin.register(ShareToken)
class ShareTokenAdmin(admin.ModelAdmin):
    list_display = ['token', 'course', 'created_by', 'visibility', 'max_uses', 'uses_count', 'is_active']
    list_filter = ['visibility', 'is_active']
    raw_id_fields = ['course', 'created_by']
