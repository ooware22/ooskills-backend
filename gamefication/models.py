"""
Gamification Models for OOSkills Platform

Covers: XP tracking, levels, streaks, achievements, leaderboard.
Follows existing patterns: UUID PKs, created_at/updated_at, French verbose names.
"""

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


# =============================================================================
# LEVEL THRESHOLDS
# =============================================================================

LEVEL_THRESHOLDS = [
    # (level, total_xp_required, title_en)
    (1,  0,    'Beginner'),
    (2,  100,  'Apprentice'),
    (3,  300,  'Student'),
    (4,  600,  'Explorer'),
    (5,  1000, 'Scholar'),
    (6,  1500, 'Expert'),
    (7,  2200, 'Master'),
    (8,  3000, 'Champion'),
    (9,  4000, 'Legend'),
    (10, 5500, 'Genius'),
]

LEVEL_TITLES_I18N = {
    1:  {'en': 'Beginner',   'fr': 'Débutant',      'ar': 'مبتدئ'},
    2:  {'en': 'Apprentice', 'fr': 'Apprenti',      'ar': 'متدرب'},
    3:  {'en': 'Student',    'fr': 'Étudiant',      'ar': 'طالب'},
    4:  {'en': 'Explorer',   'fr': 'Explorateur',   'ar': 'مستكشف'},
    5:  {'en': 'Scholar',    'fr': 'Érudit',        'ar': 'عالم'},
    6:  {'en': 'Expert',     'fr': 'Expert',        'ar': 'خبير'},
    7:  {'en': 'Master',     'fr': 'Maître',        'ar': 'أستاذ'},
    8:  {'en': 'Champion',   'fr': 'Champion',      'ar': 'بطل'},
    9:  {'en': 'Legend',     'fr': 'Légende',       'ar': 'أسطورة'},
    10: {'en': 'Genius',    'fr': 'Génie',         'ar': 'عبقري'},
}


def compute_level(total_xp: int) -> tuple:
    """
    Compute level info from total XP.

    Returns:
        (level_number, level_title_i18n, xp_for_current_level, xp_for_next_level)
    """
    current_level = 1
    current_threshold = 0
    next_threshold = LEVEL_THRESHOLDS[1][1] if len(LEVEL_THRESHOLDS) > 1 else None

    for i, (level, xp_required, _title) in enumerate(LEVEL_THRESHOLDS):
        if total_xp >= xp_required:
            current_level = level
            current_threshold = xp_required
            if i + 1 < len(LEVEL_THRESHOLDS):
                next_threshold = LEVEL_THRESHOLDS[i + 1][1]
            else:
                next_threshold = None  # Max level
        else:
            break

    title_i18n = LEVEL_TITLES_I18N.get(current_level, {'en': 'Unknown'})
    return current_level, title_i18n, current_threshold, next_threshold


# =============================================================================
# USER XP (1-to-1 with User)
# =============================================================================

class UserXP(models.Model):
    """Tracks a user's total XP, computed level, and daily streak."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='xp_profile',
    )
    total_xp = models.PositiveIntegerField('XP Total', default=0)
    level = models.PositiveIntegerField('Niveau', default=1)
    level_title = models.JSONField(
        'Titre du niveau', default=dict, blank=True,
        help_text='i18n level title, e.g. {"fr": "Débutant", "en": "Beginner"}',
    )
    streak_days = models.PositiveIntegerField('Jours consécutifs', default=0)
    longest_streak = models.PositiveIntegerField('Record de jours', default=0)
    streak_last_date = models.DateField(
        'Dernière activité', null=True, blank=True,
        help_text='Last date the user earned XP',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Profil XP'
        verbose_name_plural = 'Profils XP'
        ordering = ['-total_xp']

    def __str__(self):
        return f'{self.user} — Lv.{self.level} ({self.total_xp} XP)'

    def recalculate_level(self):
        """Recalculate level and title from total_xp."""
        level, title, _cur, _nxt = compute_level(self.total_xp)
        self.level = level
        self.level_title = title


# =============================================================================
# XP TRANSACTION (audit log)
# =============================================================================

class XPSourceType(models.TextChoices):
    LESSON = 'lesson', 'Leçon terminée'
    QUIZ = 'quiz', 'Quiz réussi'
    FINAL_QUIZ = 'final_quiz', 'Examen final réussi'
    ACHIEVEMENT = 'achievement', 'Succès débloqué'
    BONUS = 'bonus', 'Bonus'
    ENROLLMENT = 'enrollment', 'Inscription'


class XPTransaction(models.Model):
    """Audit log of every XP change for a user."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='xp_transactions',
    )
    source = models.CharField(
        'Source', max_length=20, choices=XPSourceType.choices,
    )
    amount = models.IntegerField('Montant XP', help_text='Positive = gain, negative = penalty')
    reference_id = models.CharField(
        'Référence', max_length=255, blank=True,
        help_text='UUID or identifier of the source object (lesson, quiz, etc.)',
    )
    description = models.CharField(
        'Description', max_length=255, blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Transaction XP'
        verbose_name_plural = 'Transactions XP'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'source']),
            models.Index(fields=['user', '-created_at']),
        ]

    def __str__(self):
        sign = '+' if self.amount >= 0 else ''
        return f'{self.user} {sign}{self.amount} XP ({self.source})'


# =============================================================================
# ACHIEVEMENT DEFINITION (admin-defined)
# =============================================================================

class ConditionType(models.TextChoices):
    LESSONS_COMPLETED = 'lessons_completed', 'Leçons terminées'
    QUIZZES_PASSED = 'quizzes_passed', 'Quiz réussis'
    COURSES_COMPLETED = 'courses_completed', 'Formations terminées'
    STREAK_DAYS = 'streak_days', 'Jours consécutifs'
    TOTAL_XP = 'total_xp', 'XP total atteint'
    PERFECT_QUIZ = 'perfect_quiz', 'Quiz parfait'


class AchievementDefinition(models.Model):
    """Admin-defined achievement that users can unlock."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.CharField(
        'Clé unique', max_length=50, unique=True,
        help_text='Machine-readable key, e.g. first_lesson, quiz_master',
    )
    title = models.JSONField(
        'Titre', default=dict,
        help_text='i18n: {"fr": "...", "en": "...", "ar": "..."}',
    )
    description = models.JSONField(
        'Description', default=dict,
        help_text='i18n: {"fr": "...", "en": "...", "ar": "..."}',
    )
    icon = models.CharField(
        'Icône', max_length=50, default='TrophyIcon',
        help_text='Heroicon name, e.g. AcademicCapIcon, FireIcon',
    )
    xp_reward = models.PositiveIntegerField(
        'Récompense XP', default=20,
        help_text='XP awarded when achievement is unlocked',
    )
    condition_type = models.CharField(
        'Type de condition', max_length=30, choices=ConditionType.choices,
    )
    condition_value = models.PositiveIntegerField(
        'Valeur seuil', default=1,
        help_text='Threshold value for the condition (e.g. 10 lessons)',
    )
    is_active = models.BooleanField('Actif', default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Définition de succès'
        verbose_name_plural = 'Définitions de succès'
        ordering = ['condition_type', 'condition_value']

    def __str__(self):
        title_str = self.title.get('fr', self.title.get('en', self.key))
        return f'{title_str} ({self.condition_type} >= {self.condition_value})'


# =============================================================================
# USER ACHIEVEMENT (M2M join)
# =============================================================================

class UserAchievement(models.Model):
    """Records which achievements a user has unlocked."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='achievements',
    )
    achievement = models.ForeignKey(
        AchievementDefinition,
        on_delete=models.CASCADE,
        related_name='unlocked_by',
    )
    unlocked_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = 'Succès utilisateur'
        verbose_name_plural = 'Succès utilisateurs'
        unique_together = [['user', 'achievement']]
        ordering = ['-unlocked_at']

    def __str__(self):
        return f'{self.user} — {self.achievement.key}'


# =============================================================================
# LEADERBOARD CACHE
# =============================================================================

class LeaderboardPeriod(models.TextChoices):
    WEEKLY = 'weekly', 'Hebdomadaire'
    ALLTIME = 'alltime', 'Tout temps'


class LeaderboardCache(models.Model):
    """
    Materialized leaderboard row — refreshed periodically.
    Avoids expensive ORDER BY queries on every leaderboard view.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='leaderboard_entries',
    )
    period = models.CharField(
        'Période', max_length=10, choices=LeaderboardPeriod.choices,
    )
    total_xp = models.PositiveIntegerField('XP Total', default=0)
    level = models.PositiveIntegerField('Niveau', default=1)
    rank = models.PositiveIntegerField('Classement', default=0)
    refreshed_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Cache classement'
        verbose_name_plural = 'Cache classements'
        unique_together = [['user', 'period']]
        ordering = ['period', 'rank']
        indexes = [
            models.Index(fields=['period', 'rank']),
        ]

    def __str__(self):
        return f'#{self.rank} {self.user} ({self.period})'
