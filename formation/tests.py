"""
Formation Tests — critical flow unit tests with i18n JSON fields.

Tests cover the three required flows:
1. Progress Autosave (concurrency safety)
2. Share Token Access (validation, max uses, expiry)
3. Quiz Scoring (score calculation, threshold, XP, attempts)
"""

from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from datetime import timedelta

from users.models import User
from formation.models import (
    Category, Course, CourseStatus, Section, Lesson,
    Enrollment, EnrollmentStatus, LessonProgress,
    Quiz, QuizQuestion, ShareToken, ShareVisibility,
    Certificate,
)
from formation.services.progress_service import autosave_progress
from formation.services.quiz_service import submit_quiz, QuizLimitExceeded, get_remaining_attempts
from formation.services.sharing_service import validate_and_consume_token, create_share_token
from formation.services.enrollment_service import enroll_user, AlreadyEnrolled
from formation.services.certificate_service import (
    issue_certificate, CourseNotCompleted, CertificateAlreadyIssued,
)


class FormationTestBase(TestCase):
    """Shared setup for formation tests — uses i18n JSON fields."""

    def setUp(self):
        self.user = User.objects.create_user(
            email='student@test.com', password='testpass123',
        )
        self.admin = User.objects.create_user(
            email='admin@test.com', password='testpass123',
            role='ADMIN', is_staff=True,
        )
        self.category = Category.objects.create(
            name={'fr': 'Langues', 'en': 'Languages', 'ar': 'اللغات'},
            slug='languages',
        )
        self.course = Course.objects.create(
            title='Test Course',
            slug='test-course',
            description='A test course description',
            category=self.category,
            status=CourseStatus.PUBLISHED,
            price=3900, originalPrice=6500, duration=18,
        )
        self.section = Section.objects.create(
            course=self.course,
            title='Module 1',
            type='module', sequence=10,
        )
        self.lesson1 = Lesson.objects.create(
            section=self.section,
            title='Lesson 1',
            sequence=1, duration_seconds=300,
        )
        self.lesson2 = Lesson.objects.create(
            section=self.section,
            title='Lesson 2',
            sequence=2, duration_seconds=300,
        )
        self.enrollment = Enrollment.objects.create(
            user=self.user, course=self.course,
            status=EnrollmentStatus.ACTIVE,
        )


# ═════════════════════════════════════════════════════════════════════════════
# 1. PROGRESS AUTOSAVE TESTS
# ═════════════════════════════════════════════════════════════════════════════

class ProgressAutosaveTests(FormationTestBase):
    """Test progress autosave with concurrency safety."""

    def test_create_new_progress(self):
        progress = autosave_progress(
            enrollment=self.enrollment,
            lesson=self.lesson1,
            current_slide=2, last_position=60, time_spent_delta=30,
        )
        self.assertEqual(progress.current_slide, 2)
        self.assertEqual(progress.last_position, 60)
        self.assertEqual(progress.time_spent, 30)
        self.assertFalse(progress.completed)

    def test_update_existing_progress(self):
        autosave_progress(
            enrollment=self.enrollment, lesson=self.lesson1,
            current_slide=2, last_position=60, time_spent_delta=30,
        )
        progress = autosave_progress(
            enrollment=self.enrollment, lesson=self.lesson1,
            current_slide=5, last_position=120, time_spent_delta=20,
        )
        self.assertEqual(progress.current_slide, 5)
        self.assertEqual(progress.last_position, 120)
        self.assertEqual(progress.time_spent, 50)

    def test_slide_never_goes_backwards(self):
        autosave_progress(enrollment=self.enrollment, lesson=self.lesson1, current_slide=5)
        progress = autosave_progress(enrollment=self.enrollment, lesson=self.lesson1, current_slide=3)
        self.assertEqual(progress.current_slide, 5)

    def test_mark_completed(self):
        progress = autosave_progress(enrollment=self.enrollment, lesson=self.lesson1, completed=True)
        self.assertTrue(progress.completed)
        self.assertIsNotNone(progress.completed_at)

    def test_enrollment_progress_recalculation(self):
        autosave_progress(enrollment=self.enrollment, lesson=self.lesson1, completed=True)
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.progress, Decimal('50.00'))

    def test_enrollment_completed_at_100(self):
        autosave_progress(enrollment=self.enrollment, lesson=self.lesson1, completed=True)
        autosave_progress(enrollment=self.enrollment, lesson=self.lesson2, completed=True)
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.progress, Decimal('100.00'))
        self.assertEqual(self.enrollment.status, EnrollmentStatus.COMPLETED)
        self.assertIsNotNone(self.enrollment.completed_at)


# ═════════════════════════════════════════════════════════════════════════════
# 2. SHARE TOKEN ACCESS TESTS
# ═════════════════════════════════════════════════════════════════════════════

class ShareTokenAccessTests(FormationTestBase):

    def test_create_token(self):
        token = create_share_token(course=self.course, user=self.user, visibility='token', max_uses=5)
        self.assertTrue(len(token.token) > 10)
        self.assertTrue(token.is_valid)

    def test_validate_valid_token(self):
        token = create_share_token(course=self.course, user=self.user)
        result = validate_and_consume_token(token.token)
        self.assertIsNotNone(result)
        token.refresh_from_db()
        self.assertEqual(token.uses_count, 1)

    def test_max_uses_enforced(self):
        token = create_share_token(course=self.course, user=self.user, max_uses=2)
        validate_and_consume_token(token.token)
        validate_and_consume_token(token.token)
        result = validate_and_consume_token(token.token)
        self.assertIsNone(result)

    def test_expired_token_invalid(self):
        token = create_share_token(course=self.course, user=self.user, expires_in_days=0)
        token.expires_at = timezone.now() - timedelta(hours=1)
        token.save()
        result = validate_and_consume_token(token.token)
        self.assertIsNone(result)

    def test_deactivated_token_invalid(self):
        token = create_share_token(course=self.course, user=self.user)
        token.is_active = False
        token.save()
        result = validate_and_consume_token(token.token)
        self.assertIsNone(result)

    def test_nonexistent_token_returns_none(self):
        self.assertIsNone(validate_and_consume_token('nonexistent-token'))


# ═════════════════════════════════════════════════════════════════════════════
# 3. QUIZ SCORING TESTS
# ═════════════════════════════════════════════════════════════════════════════

class QuizScoringTests(FormationTestBase):

    def setUp(self):
        super().setUp()
        self.quiz = Quiz.objects.create(
            section=self.section,
            title='Test Quiz',
            pass_threshold=70, max_attempts=3, xp_reward=10,
        )
        self.q1 = QuizQuestion.objects.create(
            quiz=self.quiz,
            question='Q1?',
            options=['A', 'B', 'C'],
            correct_answer=0, sequence=1,
        )
        self.q2 = QuizQuestion.objects.create(
            quiz=self.quiz,
            question='Q2?',
            options=['X', 'Y', 'Z'],
            correct_answer=1, sequence=2,
        )
        self.q3 = QuizQuestion.objects.create(
            quiz=self.quiz,
            question='Q3?',
            options=['1', '2', '3'],
            correct_answer=2, sequence=3,
        )

    def test_perfect_score(self):
        answers = {str(self.q1.id): 0, str(self.q2.id): 1, str(self.q3.id): 2}
        attempt = submit_quiz(self.enrollment, self.quiz, answers)
        self.assertEqual(attempt.score, Decimal('100.00'))
        self.assertTrue(attempt.passed)
        self.assertEqual(attempt.xp_earned, 10)
        self.assertEqual(attempt.attempt_number, 1)

    def test_failing_score(self):
        answers = {str(self.q1.id): 2, str(self.q2.id): 2, str(self.q3.id): 0}
        attempt = submit_quiz(self.enrollment, self.quiz, answers)
        self.assertEqual(attempt.score, Decimal('0.00'))
        self.assertFalse(attempt.passed)
        self.assertEqual(attempt.xp_earned, 0)

    def test_threshold_edge_fail(self):
        answers = {str(self.q1.id): 0, str(self.q2.id): 1, str(self.q3.id): 0}
        attempt = submit_quiz(self.enrollment, self.quiz, answers)
        self.assertEqual(attempt.score, Decimal('66.67'))
        self.assertFalse(attempt.passed)

    def test_feedback_generated(self):
        answers = {str(self.q1.id): 0}
        attempt = submit_quiz(self.enrollment, self.quiz, answers)
        self.assertEqual(len(attempt.feedback), 3)
        self.assertIn('is_correct', attempt.feedback[0])

    def test_attempt_counter_increments(self):
        answers = {str(self.q1.id): 0}
        a1 = submit_quiz(self.enrollment, self.quiz, answers)
        a2 = submit_quiz(self.enrollment, self.quiz, answers)
        self.assertEqual(a1.attempt_number, 1)
        self.assertEqual(a2.attempt_number, 2)

    def test_max_attempts_enforced(self):
        answers = {str(self.q1.id): 0}
        for _ in range(3):
            submit_quiz(self.enrollment, self.quiz, answers)
        with self.assertRaises(QuizLimitExceeded):
            submit_quiz(self.enrollment, self.quiz, answers)

    def test_remaining_attempts(self):
        self.assertEqual(get_remaining_attempts(self.enrollment, self.quiz), 3)
        submit_quiz(self.enrollment, self.quiz, {str(self.q1.id): 0})
        self.assertEqual(get_remaining_attempts(self.enrollment, self.quiz), 2)


# ═════════════════════════════════════════════════════════════════════════════
# 4. ENROLLMENT TESTS
# ═════════════════════════════════════════════════════════════════════════════

class EnrollmentTests(FormationTestBase):

    def test_enroll_user(self):
        new_user = User.objects.create_user(email='new@test.com', password='pass123')
        enrollment = enroll_user(new_user, self.course)
        self.assertEqual(enrollment.status, EnrollmentStatus.ACTIVE)

    def test_duplicate_enrollment_raises(self):
        with self.assertRaises(AlreadyEnrolled):
            enroll_user(self.user, self.course)


# ═════════════════════════════════════════════════════════════════════════════
# 5. CERTIFICATE TESTS
# ═════════════════════════════════════════════════════════════════════════════

class CertificateTests(FormationTestBase):

    def test_issue_certificate(self):
        self.enrollment.status = EnrollmentStatus.COMPLETED
        self.enrollment.save()
        cert = issue_certificate(self.enrollment, score=85.5)
        self.assertTrue(cert.code.startswith('OOS-'))

    def test_cannot_issue_without_completion(self):
        with self.assertRaises(CourseNotCompleted):
            issue_certificate(self.enrollment)

    def test_duplicate_certificate_raises(self):
        self.enrollment.status = EnrollmentStatus.COMPLETED
        self.enrollment.save()
        issue_certificate(self.enrollment)
        with self.assertRaises(CertificateAlreadyIssued):
            issue_certificate(self.enrollment)


# ═════════════════════════════════════════════════════════════════════════════
# 6. FINAL QUIZ TESTS
# ═════════════════════════════════════════════════════════════════════════════

class FinalQuizTests(FormationTestBase):
    """Tests for the final quiz generation and submission flow."""

    def setUp(self):
        super().setUp()
        from formation.models import FinalQuiz

        # Create a section quiz with 3 questions for the test course
        self.quiz = Quiz.objects.create(
            section=self.section,
            title='Module 1 Quiz',
            pass_threshold=70,
            max_attempts=3,
        )
        self.q1 = QuizQuestion.objects.create(
            quiz=self.quiz, question='What is 1+1?',
            options=['1', '2', '3', '4'],
            correct_answer=1, sequence=1,
        )
        self.q2 = QuizQuestion.objects.create(
            quiz=self.quiz, question='What is 2+2?',
            options=['2', '3', '4', '5'],
            correct_answer=2, sequence=2,
        )
        self.q3 = QuizQuestion.objects.create(
            quiz=self.quiz, question='What is 3+3?',
            options=['4', '5', '6', '7'],
            correct_answer=2, sequence=3,
        )

        self.final_quiz = FinalQuiz.objects.create(
            course=self.course,
            title='Examen Final',
            num_questions=2,  # only 2 for testing
            pass_threshold=70,
            max_attempts=3,
            xp_reward=50,
        )
        # Complete the enrollment so the student can take the final quiz
        self.enrollment.status = EnrollmentStatus.COMPLETED
        self.enrollment.save()

    def test_generate_questions(self):
        """Should return random questions from section quizzes."""
        from formation.services.final_quiz_service import generate_final_quiz_questions

        questions = generate_final_quiz_questions(self.enrollment)
        self.assertEqual(len(questions), 2)
        # Each question dict should have these keys
        for q in questions:
            self.assertIn('id', q)
            self.assertIn('question', q)
            self.assertIn('options', q)

    def test_generate_rejects_incomplete_enrollment(self):
        """Cannot generate quiz if enrollment is not completed."""
        from formation.services.final_quiz_service import (
            generate_final_quiz_questions, CourseNotCompleted,
        )
        self.enrollment.status = EnrollmentStatus.ACTIVE
        self.enrollment.save()
        with self.assertRaises(CourseNotCompleted):
            generate_final_quiz_questions(self.enrollment)

    def test_submit_passing_score(self):
        """Passing score should create cert and return passed=True."""
        from formation.services.final_quiz_service import (
            generate_final_quiz_questions, submit_final_quiz,
        )
        from formation.models import Certificate

        questions = generate_final_quiz_questions(self.enrollment)
        question_ids = [q['id'] for q in questions]

        # Build answers that get a perfect score
        from formation.models import QuizQuestion
        answers = {}
        for qid in question_ids:
            qq = QuizQuestion.objects.get(id=qid)
            answers[qid] = qq.correct_answer

        attempt = submit_final_quiz(self.enrollment, answers, question_ids)
        self.assertTrue(attempt.passed)
        self.assertEqual(attempt.score, 100)
        self.assertEqual(attempt.xp_earned, 50)

        # Certificate should have been auto-issued
        self.assertTrue(
            Certificate.objects.filter(
                user=self.user, course=self.course,
            ).exists()
        )

    def test_submit_failing_score(self):
        """Failing score should not issue certificate."""
        from formation.services.final_quiz_service import (
            generate_final_quiz_questions, submit_final_quiz,
        )
        from formation.models import Certificate

        questions = generate_final_quiz_questions(self.enrollment)
        question_ids = [q['id'] for q in questions]

        # All wrong answers
        answers = {qid: 999 for qid in question_ids}

        attempt = submit_final_quiz(self.enrollment, answers, question_ids)
        self.assertFalse(attempt.passed)
        self.assertEqual(attempt.score, 0)
        self.assertEqual(attempt.xp_earned, 0)
        self.assertFalse(
            Certificate.objects.filter(
                user=self.user, course=self.course,
            ).exists()
        )

    def test_max_attempts_enforced(self):
        """Should raise FinalQuizLimitExceeded after max attempts."""
        from formation.services.final_quiz_service import (
            generate_final_quiz_questions, submit_final_quiz,
            FinalQuizLimitExceeded,
        )

        self.final_quiz.max_attempts = 1
        self.final_quiz.save()

        questions = generate_final_quiz_questions(self.enrollment)
        question_ids = [q['id'] for q in questions]
        answers = {qid: 999 for qid in question_ids}
        submit_final_quiz(self.enrollment, answers, question_ids)

        # Second attempt should fail
        with self.assertRaises(FinalQuizLimitExceeded):
            generate_final_quiz_questions(self.enrollment)

    def test_remaining_attempts(self):
        """get_final_quiz_remaining_attempts returns correct count."""
        from formation.services.final_quiz_service import (
            generate_final_quiz_questions, submit_final_quiz,
            get_final_quiz_remaining_attempts,
        )

        remaining = get_final_quiz_remaining_attempts(self.enrollment, self.final_quiz)
        self.assertEqual(remaining, 3)

        questions = generate_final_quiz_questions(self.enrollment)
        question_ids = [q['id'] for q in questions]
        answers = {qid: 999 for qid in question_ids}
        submit_final_quiz(self.enrollment, answers, question_ids)

        remaining = get_final_quiz_remaining_attempts(self.enrollment, self.final_quiz)
        self.assertEqual(remaining, 2)


# ═════════════════════════════════════════════════════════════════════════════
# 7. CERTIFICATE PDF TESTS
# ═════════════════════════════════════════════════════════════════════════════

class CertificatePDFTests(TestCase):
    """Tests for PDF certificate generation."""

    def test_generate_pdf_bytes(self):
        """PDF generation should return valid bytes."""
        from formation.services.pdf_service import generate_certificate_pdf
        from datetime import datetime

        pdf_bytes = generate_certificate_pdf(
            student_name='Test Student',
            course_title='Introduction to Django',
            score=92.5,
            code='OOS-TEST123456',
            issued_at=datetime(2026, 2, 17),
        )
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(len(pdf_bytes) > 0)
        # PDF files start with %PDF
        self.assertTrue(pdf_bytes[:4] == b'%PDF')

    def test_pdf_with_long_title(self):
        """PDF should handle long course titles gracefully."""
        from formation.services.pdf_service import generate_certificate_pdf

        pdf_bytes = generate_certificate_pdf(
            student_name='A Very Long Student Name That Is Quite Unusual',
            course_title='A Very Long Course Title That Should Be Auto-Sized To Fit',
            score=100,
            code='OOS-LONGTEST000',
        )
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes[:4] == b'%PDF')
