"""
Gamification Tests — unit tests for XP, levels, streaks, achievements, signals.

Follows the existing formation/tests.py patterns.
"""

from decimal import Decimal
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from users.models import User
from formation.models import (
    Category, Course, CourseStatus, Section, Lesson,
    Enrollment, EnrollmentStatus, LessonProgress,
    Quiz, QuizQuestion, QuizAttempt,
)
from gamefication.models import (
    LEVEL_THRESHOLDS,
    AchievementDefinition,
    ConditionType,
    LeaderboardPeriod,
    UserAchievement,
    UserXP,
    XPSourceType,
    XPTransaction,
    compute_level,
)
from gamefication.services.xp_service import award_xp, get_or_create_xp_profile
from gamefication.services.achievement_service import check_achievements
from gamefication.services.leaderboard_service import refresh_leaderboard, get_leaderboard


class GamificationTestBase(TestCase):
    """Shared setup for gamification tests."""

    def setUp(self):
        self.user = User.objects.create_user(
            email='student@test.com', password='testpass123',
        )
        self.user2 = User.objects.create_user(
            email='student2@test.com', password='testpass123',
        )
        self.category = Category.objects.create(
            name={'fr': 'Test', 'en': 'Test', 'ar': 'اختبار'},
            slug='test-cat',
        )
        self.course = Course.objects.create(
            title='Test Course', slug='test-course',
            description='A test course',
            category=self.category,
            status=CourseStatus.PUBLISHED,
            price=0, duration=10,
        )
        self.section = Section.objects.create(
            course=self.course, title='Module 1',
            type='module', sequence=10,
        )
        self.lesson1 = Lesson.objects.create(
            section=self.section, title='Lesson 1',
            sequence=1, duration_seconds=300,
        )
        self.lesson2 = Lesson.objects.create(
            section=self.section, title='Lesson 2',
            sequence=2, duration_seconds=300,
        )
        self.enrollment = Enrollment.objects.create(
            user=self.user, course=self.course,
            status=EnrollmentStatus.ACTIVE,
        )


# ═════════════════════════════════════════════════════════════════════════════
# 1. LEVEL COMPUTATION TESTS
# ═════════════════════════════════════════════════════════════════════════════

class LevelComputationTests(TestCase):

    def test_zero_xp_is_level_1(self):
        level, title, cur, nxt = compute_level(0)
        self.assertEqual(level, 1)
        self.assertEqual(cur, 0)
        self.assertEqual(nxt, 100)

    def test_exact_threshold(self):
        level, title, cur, nxt = compute_level(100)
        self.assertEqual(level, 2)
        self.assertEqual(cur, 100)
        self.assertEqual(nxt, 300)

    def test_between_levels(self):
        level, title, cur, nxt = compute_level(250)
        self.assertEqual(level, 2)
        self.assertEqual(cur, 100)
        self.assertEqual(nxt, 300)

    def test_max_level(self):
        level, title, cur, nxt = compute_level(9999)
        self.assertEqual(level, 10)
        self.assertIsNone(nxt)

    def test_all_thresholds(self):
        for lvl, xp_req, _title in LEVEL_THRESHOLDS:
            level, _t, _c, _n = compute_level(xp_req)
            self.assertEqual(level, lvl, f'XP {xp_req} should be level {lvl}')


# ═════════════════════════════════════════════════════════════════════════════
# 2. XP AWARD TESTS
# ═════════════════════════════════════════════════════════════════════════════

class XPAwardTests(GamificationTestBase):

    def test_award_creates_transaction(self):
        # Note: enrollment signal already created 1 transaction (+5 XP)
        initial_count = XPTransaction.objects.filter(user=self.user).count()
        award_xp(self.user, 50, XPSourceType.LESSON, 'ref-1')
        self.assertEqual(XPTransaction.objects.filter(user=self.user).count(), initial_count + 1)

    def test_award_updates_total_xp(self):
        # Enrollment signal adds 5 XP in setUp
        award_xp(self.user, 50, XPSourceType.LESSON, 'ref-1')
        profile = UserXP.objects.get(user=self.user)
        self.assertEqual(profile.total_xp, 55)  # 5 (enrollment) + 50

    def test_multiple_awards_accumulate(self):
        # Enrollment signal adds 5 XP in setUp
        award_xp(self.user, 50, XPSourceType.LESSON, 'ref-1')
        award_xp(self.user, 60, XPSourceType.QUIZ, 'ref-2')
        profile = UserXP.objects.get(user=self.user)
        self.assertEqual(profile.total_xp, 115)  # 5 + 50 + 60

    def test_level_up_detected(self):
        result = award_xp(self.user, 100, XPSourceType.BONUS, 'ref-1')
        self.assertTrue(result['leveled_up'])
        self.assertEqual(result['new_level'], 2)

    def test_no_level_up(self):
        result = award_xp(self.user, 10, XPSourceType.BONUS, 'ref-1')
        self.assertFalse(result['leveled_up'])
        self.assertEqual(result['new_level'], 1)

    def test_xp_cannot_go_negative(self):
        award_xp(self.user, 10, XPSourceType.BONUS, 'ref-1')
        award_xp(self.user, -100, XPSourceType.BONUS, 'ref-2')
        profile = UserXP.objects.get(user=self.user)
        self.assertEqual(profile.total_xp, 0)


# ═════════════════════════════════════════════════════════════════════════════
# 3. STREAK TESTS
# ═════════════════════════════════════════════════════════════════════════════

class StreakTests(GamificationTestBase):

    def test_first_activity_starts_streak(self):
        result = award_xp(self.user, 10, XPSourceType.LESSON, 'ref-1')
        self.assertEqual(result['streak_days'], 1)

    def test_same_day_no_double_count(self):
        award_xp(self.user, 10, XPSourceType.LESSON, 'ref-1')
        result = award_xp(self.user, 10, XPSourceType.LESSON, 'ref-2')
        self.assertEqual(result['streak_days'], 1)

    def test_streak_resets_after_gap(self):
        result = award_xp(self.user, 10, XPSourceType.LESSON, 'ref-1')
        # Simulate a gap by setting streak_last_date to 3 days ago
        profile = UserXP.objects.get(user=self.user)
        profile.streak_last_date = timezone.now().date() - timedelta(days=3)
        profile.streak_days = 5
        profile.save()

        result = award_xp(self.user, 10, XPSourceType.LESSON, 'ref-2')
        self.assertEqual(result['streak_days'], 1)  # Reset


# ═════════════════════════════════════════════════════════════════════════════
# 4. ACHIEVEMENT TESTS
# ═════════════════════════════════════════════════════════════════════════════

class AchievementTests(GamificationTestBase):

    def setUp(self):
        super().setUp()
        # Create some achievement definitions
        self.ach_first_xp = AchievementDefinition.objects.create(
            key='first_xp',
            title={'fr': 'Premier XP', 'en': 'First XP'},
            description={'fr': 'Gagner du XP', 'en': 'Earn XP'},
            condition_type=ConditionType.TOTAL_XP,
            condition_value=10,
            xp_reward=5,
        )
        self.ach_lesson_5 = AchievementDefinition.objects.create(
            key='lesson_5',
            title={'fr': '5 Leçons', 'en': '5 Lessons'},
            description={'fr': 'Terminer 5 leçons', 'en': 'Complete 5 lessons'},
            condition_type=ConditionType.LESSONS_COMPLETED,
            condition_value=5,
            xp_reward=20,
        )

    def test_achievement_unlocked_when_condition_met(self):
        award_xp(self.user, 50, XPSourceType.BONUS, 'ref-1')
        # first_xp achievement requires 10 XP total — should be unlocked
        self.assertTrue(
            UserAchievement.objects.filter(
                user=self.user, achievement=self.ach_first_xp,
            ).exists()
        )

    def test_achievement_xp_bonus_awarded(self):
        # 5 (enrollment) + 50 (manual) + 5 (achievement reward) = 60
        award_xp(self.user, 50, XPSourceType.BONUS, 'ref-1')
        profile = UserXP.objects.get(user=self.user)
        self.assertEqual(profile.total_xp, 60)

    def test_no_duplicate_achievement_unlock(self):
        award_xp(self.user, 50, XPSourceType.BONUS, 'ref-1')
        award_xp(self.user, 50, XPSourceType.BONUS, 'ref-2')
        count = UserAchievement.objects.filter(
            user=self.user, achievement=self.ach_first_xp,
        ).count()
        self.assertEqual(count, 1)

    def test_unmet_condition_not_unlocked(self):
        award_xp(self.user, 50, XPSourceType.BONUS, 'ref-1')
        # lesson_5 requires 5 completed lessons — should NOT be unlocked
        self.assertFalse(
            UserAchievement.objects.filter(
                user=self.user, achievement=self.ach_lesson_5,
            ).exists()
        )


# ═════════════════════════════════════════════════════════════════════════════
# 5. SIGNAL TESTS
# ═════════════════════════════════════════════════════════════════════════════

class SignalTests(GamificationTestBase):

    def test_lesson_completion_awards_xp(self):
        """Completing a lesson via autosave should trigger XP via signal."""
        from formation.services.progress_service import autosave_progress

        autosave_progress(
            enrollment=self.enrollment,
            lesson=self.lesson1,
            completed=True,
        )
        # Signal should have awarded 10 XP for lesson completion
        self.assertTrue(
            XPTransaction.objects.filter(
                user=self.user,
                source=XPSourceType.LESSON,
                reference_id=str(self.lesson1.id),
            ).exists()
        )

    def test_lesson_completion_no_double_award(self):
        """Saving progress again should not double-award XP."""
        from formation.services.progress_service import autosave_progress

        autosave_progress(enrollment=self.enrollment, lesson=self.lesson1, completed=True)
        autosave_progress(enrollment=self.enrollment, lesson=self.lesson1, completed=True)

        count = XPTransaction.objects.filter(
            user=self.user,
            source=XPSourceType.LESSON,
            reference_id=str(self.lesson1.id),
        ).count()
        self.assertEqual(count, 1)

    def test_quiz_pass_awards_xp(self):
        """Passing a quiz should trigger XP via signal."""
        quiz = Quiz.objects.create(
            section=self.section, title='Test Quiz',
            pass_threshold=50, max_attempts=3, xp_reward=15,
        )
        q1 = QuizQuestion.objects.create(
            quiz=quiz, question='Q1?',
            options=['A', 'B'], correct_answer=0, sequence=1,
        )

        from formation.services.quiz_service import submit_quiz
        submit_quiz(self.enrollment, quiz, {str(q1.id): 0})

        self.assertTrue(
            XPTransaction.objects.filter(
                user=self.user,
                source=XPSourceType.QUIZ,
                reference_id=str(quiz.id),
            ).exists()
        )


# ═════════════════════════════════════════════════════════════════════════════
# 6. LEADERBOARD TESTS
# ═════════════════════════════════════════════════════════════════════════════

class LeaderboardTests(GamificationTestBase):

    def test_refresh_alltime_leaderboard(self):
        award_xp(self.user, 200, XPSourceType.BONUS, 'ref-1')
        award_xp(self.user2, 100, XPSourceType.BONUS, 'ref-2')

        refresh_leaderboard(LeaderboardPeriod.ALLTIME)
        entries = list(get_leaderboard(LeaderboardPeriod.ALLTIME))

        self.assertGreaterEqual(len(entries), 2)
        # User with more XP should be ranked first
        self.assertEqual(entries[0].user, self.user)
        self.assertEqual(entries[0].rank, 1)
        self.assertEqual(entries[1].user, self.user2)
        self.assertEqual(entries[1].rank, 2)

    def test_refresh_weekly_leaderboard(self):
        award_xp(self.user, 50, XPSourceType.BONUS, 'ref-1')
        refresh_leaderboard(LeaderboardPeriod.WEEKLY)
        entries = list(get_leaderboard(LeaderboardPeriod.WEEKLY))
        self.assertGreaterEqual(len(entries), 1)


# ═════════════════════════════════════════════════════════════════════════════
# 7. XP PROFILE API TESTS
# ═════════════════════════════════════════════════════════════════════════════

class XPProfileTests(GamificationTestBase):

    def test_get_or_create_profile(self):
        # self.user already has 5 XP from enrollment signal in setUp
        # Use a fresh user with no enrollment to test default profile
        fresh_user = User.objects.create_user(email='fresh@test.com', password='pass')
        profile = get_or_create_xp_profile(fresh_user)
        self.assertEqual(profile.total_xp, 0)
        self.assertEqual(profile.level, 1)

    def test_profile_created_on_first_award(self):
        new_user = User.objects.create_user(email='new@test.com', password='pass')
        award_xp(new_user, 10, XPSourceType.BONUS, 'ref-1')
        self.assertTrue(UserXP.objects.filter(user=new_user).exists())
