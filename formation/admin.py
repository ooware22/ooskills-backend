"""
Formation Admin — register all models with inlines for efficient editing.

All translatable fields are JSONFields ({"fr": ..., "en": ..., "ar": ...}).
"""

from django.contrib import admin
from formation.models import (
    Category, Certificate, Course, CourseMaterial, Enrollment,
    Lesson, LessonNote, LessonProgress, Order, OrderItem,
    QuizAttempt, Quiz, QuizQuestion, Section, Module, ShareToken,
)


# ─── Inlines ─────────────────────────────────────────────────────────────────

class SectionInline(admin.TabularInline):
    model = Section
    extra = 0
    fields = ['title', 'type', 'sequence', 'audioFileIndex']
    ordering = ['sequence']


class CourseMaterialInline(admin.TabularInline):
    model = CourseMaterial
    extra = 0
    fields = ['name', 'type', 'size', 'file', 'url', 'sequence']
    ordering = ['sequence']


class ModuleInline(admin.TabularInline):
    model = Module
    extra = 0
    fields = ['title', 'sequence', 'audioFileIndex']
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
    inlines = [SectionInline, CourseMaterialInline]
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

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path('import-zip/', self.admin_site.admin_view(self.import_zip_view), name='course_import_zip'),
            path('import-zip/confirm/', self.admin_site.admin_view(self.import_zip_confirm_view), name='course_import_zip_confirm'),
        ]
        return custom_urls + urls

    def import_zip_view(self, request):
        from formation.forms import CourseImportZipForm
        from formation.services.zip_import_service import parse_zip_plan
        from django.shortcuts import render
        import tempfile
        import os
        
        if request.method == 'POST':
            form = CourseImportZipForm(request.POST, request.FILES)
            if form.is_valid():
                zip_file = request.FILES['zip_file']
                category = form.cleaned_data['category']
                instructor = form.cleaned_data['instructor']
                
                # Save ZIP temporarily to pass its path to confirm view
                fd, temp_zip_path = tempfile.mkstemp(suffix='.zip', prefix='ooskills_up_')
                with os.fdopen(fd, 'wb') as f:
                    for chunk in zip_file.chunks():
                        f.write(chunk)
                
                plan = parse_zip_plan(temp_zip_path)
                
                context = dict(
                    self.admin_site.each_context(request),
                    title='Prévisualisation et Plan',
                    plan=plan,
                    temp_zip_file=temp_zip_path,
                    category_id=category.id if category else '',
                    instructor_id=instructor.id if instructor else '',
                    opts=self.model._meta,
                )
                return render(request, "admin/formation/course/import_plan_preview.html", context)
        else:
            form = CourseImportZipForm()
            
        context = dict(
            self.admin_site.each_context(request),
            title='Importer une Formation (ZIP)',
            form=form,
            opts=self.model._meta,
        )
        return render(request, "admin/formation/course/import_zip.html", context)
        
    def import_zip_confirm_view(self, request):
        from formation.services.zip_import_service import import_course_from_zip
        from formation.models import Category
        from django.contrib.auth import get_user_model
        from django.contrib import messages
        from django.shortcuts import redirect
        from django.urls import reverse
        from django.db import transaction
        import os
        
        if request.method == 'POST':
            temp_zip_path = request.POST.get('temp_zip_file')
            category_id = request.POST.get('category_id')
            instructor_id = request.POST.get('instructor_id')
            
            if temp_zip_path and os.path.exists(temp_zip_path):
                category = Category.objects.filter(id=category_id).first() if category_id else None
                User = get_user_model()
                instructor = User.objects.filter(id=instructor_id).first() if instructor_id else None
                
                try:
                    with transaction.atomic():
                        import_course_from_zip(temp_zip_path, category, instructor)
                    messages.success(request, "La formation a été importée avec succès !")
                except Exception as e:
                    messages.error(request, f"Erreur lors de l'importation: {e}")
                finally:
                    try:
                        os.remove(temp_zip_path)
                    except:
                        pass
            else:
                messages.error(request, "Fichier zip temporaire introuvable ou invalide.")
                
            return redirect(reverse('admin:formation_course_changelist'))
            
        return redirect(reverse('admin:formation_course_changelist'))


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = ['title', 'course', 'type', 'sequence']
    list_filter = ['type']
    raw_id_fields = ['course']
    inlines = [ModuleInline]


@admin.register(Module)
class ModuleAdmin(admin.ModelAdmin):
    list_display = ['title', 'section', 'sequence']
    raw_id_fields = ['section']
    inlines = [LessonInline]


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ['title', 'module', 'type', 'sequence', 'duration_seconds']
    list_filter = ['type']
    raw_id_fields = ['module']


@admin.register(CourseMaterial)
class CourseMaterialAdmin(admin.ModelAdmin):
    list_display = ['name', 'course', 'type', 'size', 'sequence']
    list_filter = ['type']
    raw_id_fields = ['course']


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
