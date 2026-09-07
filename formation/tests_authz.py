"""
Authorization & business-logic regression tests for the formation API.

These are HTTP-layer tests (APITestCase) — they drive real requests through the
permission and serializer stack, which the existing service-level tests do not.
Each one pins a finding from the September 2026 penetration test so it cannot
silently regress:

    F-01  Payment/entitlement required before enrolling in a paid course.
    F-02  Answer key (correct_answer/explanation) never reaches students.
    N-01  ...including through the nested course-detail payload.
    F-04  Promo-code listing is admin-only.
    F-05  Share tokens require course access to mint.
"""

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status

from users.models import User
from formation.models import (
    Category, Course, CourseStatus, Section, Module, Lesson,
    Enrollment, EnrollmentStatus, Quiz, QuizQuestion,
    Order, OrderItem, OrderStatus, PromoCode,
)


class AuthzTestBase(APITestCase):
    """Four actors + a free course, a paid course, and a quiz with answers."""

    def setUp(self):
        self.anon = None
        self.user = User.objects.create_user(
            email='student@test.com', password='pw', role='USER',
        )
        self.other = User.objects.create_user(
            email='other@test.com', password='pw', role='USER',
        )
        self.admin = User.objects.create_user(
            email='admin@test.com', password='pw', role='ADMIN', is_staff=True,
        )
        self.category = Category.objects.create(
            name={'fr': 'Cat', 'en': 'Cat', 'ar': 'Cat'}, slug='cat',
        )
        self.free_course = Course.objects.create(
            title='Free', slug='free-course', description='d',
            category=self.category, status=CourseStatus.PUBLISHED,
            price=0, is_free=True,
        )
        self.paid_course = Course.objects.create(
            title='Paid', slug='paid-course', description='d',
            category=self.category, status=CourseStatus.PUBLISHED,
            price=3900, originalPrice=3900,
        )
        self.section = Section.objects.create(
            course=self.paid_course, title='S1', type='module', sequence=10,
        )
        self.quiz = Quiz.objects.create(section=self.section, title='Q1', pass_threshold=70)
        self.question = QuizQuestion.objects.create(
            quiz=self.quiz,
            question={'fr': 'Q?', 'en': 'Q?', 'ar': 'Q?'},
            options=['a', 'b', 'c', 'd'],
            correct_answer=2,
            explanation={'fr': 'because', 'en': 'because', 'ar': 'because'},
            sequence=1,
        )

    def _paid_order(self, user, course):
        order = Order.objects.create(user=user, status=OrderStatus.PAID, total=course.price)
        OrderItem.objects.create(order=order, course=course, price=course.price)
        return order


# ═════════════════════════════════════════════════════════════════════════════
# F-01 — Enrollment requires payment for paid courses
# ═════════════════════════════════════════════════════════════════════════════

class EnrollmentPaymentTests(AuthzTestBase):
    URL = '/api/formation/enrollments/'

    def test_anonymous_cannot_enroll(self):
        resp = self.client.post(self.URL, {'courseId': str(self.paid_course.id)}, format='json')
        self.assertIn(resp.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_free_course_enrolls_without_order(self):
        self.client.force_authenticate(self.user)
        resp = self.client.post(self.URL, {'courseId': str(self.free_course.id)}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            Enrollment.objects.filter(user=self.user, course=self.free_course).exists()
        )

    def test_paid_course_without_order_is_blocked(self):
        """The core F-01 regression: no paid order → 402, no enrollment."""
        self.client.force_authenticate(self.user)
        resp = self.client.post(self.URL, {'courseId': str(self.paid_course.id)}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_402_PAYMENT_REQUIRED)
        self.assertFalse(
            Enrollment.objects.filter(user=self.user, course=self.paid_course).exists()
        )

    def test_pending_order_is_not_enough(self):
        self.client.force_authenticate(self.user)
        order = Order.objects.create(user=self.user, status=OrderStatus.PENDING, total=3900)
        OrderItem.objects.create(order=order, course=self.paid_course, price=3900)
        resp = self.client.post(self.URL, {'courseId': str(self.paid_course.id)}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_402_PAYMENT_REQUIRED)

    def test_failed_order_is_not_enough(self):
        self.client.force_authenticate(self.user)
        order = Order.objects.create(user=self.user, status=OrderStatus.FAILED, total=3900)
        OrderItem.objects.create(order=order, course=self.paid_course, price=3900)
        resp = self.client.post(self.URL, {'courseId': str(self.paid_course.id)}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_402_PAYMENT_REQUIRED)

    def test_refunded_order_is_not_enough(self):
        self.client.force_authenticate(self.user)
        order = Order.objects.create(user=self.user, status=OrderStatus.REFUNDED, total=3900)
        OrderItem.objects.create(order=order, course=self.paid_course, price=3900)
        resp = self.client.post(self.URL, {'courseId': str(self.paid_course.id)}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_402_PAYMENT_REQUIRED)

    def test_another_users_paid_order_does_not_grant_access(self):
        """Entitlement is per-user: someone else's paid order must not count."""
        self._paid_order(self.other, self.paid_course)
        self.client.force_authenticate(self.user)
        resp = self.client.post(self.URL, {'courseId': str(self.paid_course.id)}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_402_PAYMENT_REQUIRED)

    def test_paid_order_grants_enrollment(self):
        self._paid_order(self.user, self.paid_course)
        self.client.force_authenticate(self.user)
        resp = self.client.post(self.URL, {'courseId': str(self.paid_course.id)}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            Enrollment.objects.filter(user=self.user, course=self.paid_course).exists()
        )


# ═════════════════════════════════════════════════════════════════════════════
# F-02 / N-01 — Answer key never leaks to students
# ═════════════════════════════════════════════════════════════════════════════

class QuizAnswerExposureTests(AuthzTestBase):

    def _assert_no_answers(self, blob):
        """Recursively assert no answer-key field appears anywhere in a payload."""
        text = str(blob)
        self.assertNotIn('correct_answer', text)
        self.assertNotIn('explanation', text)

    def test_quiz_questions_endpoint_is_admin_only(self):
        url = '/api/formation/quiz-questions/'
        # Anonymous
        self.assertIn(
            self.client.get(url).status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )
        # Regular user
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get(url).status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_read_quiz_questions_with_answers(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.get('/api/formation/quiz-questions/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('correct_answer', str(resp.data))

    def test_nested_quiz_serializer_has_no_answers(self):
        """/quizzes/ nested questions must be answer-free for a student."""
        self.client.force_authenticate(self.user)
        resp = self.client.get(f'/api/formation/quizzes/?section={self.section.id}')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self._assert_no_answers(resp.data)

    def test_course_detail_payload_has_no_answers(self):
        """N-01: the public course-detail tree must not carry the answer key."""
        resp = self.client.get(f'/api/formation/courses/{self.paid_course.slug}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self._assert_no_answers(resp.data)

    def test_sections_payload_has_no_answers(self):
        resp = self.client.get(f'/api/formation/sections/?course={self.paid_course.slug}')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self._assert_no_answers(resp.data)


# ═════════════════════════════════════════════════════════════════════════════
# F-04 — Promo-code listing is admin-only
# ═════════════════════════════════════════════════════════════════════════════

class PromoCodeVisibilityTests(AuthzTestBase):
    URL = '/api/formation/promo-codes/'

    def setUp(self):
        super().setUp()
        self.promo = PromoCode.objects.create(
            code='SUMMER50', discount_type='fixed', discount_value='1000.00',
            max_uses_per_user=1, is_active=True,
        )

    def test_anonymous_cannot_list(self):
        self.assertIn(
            self.client.get(self.URL).status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )

    def test_regular_user_cannot_list(self):
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get(self.URL).status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_list(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.get(self.URL)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_regular_user_can_still_validate(self):
        """The user-facing validate action must remain available."""
        self.client.force_authenticate(self.user)
        resp = self.client.post(
            f'{self.URL}validate/',
            {'code': 'SUMMER50', 'course_id': str(self.paid_course.id)},
            format='json',
        )
        # 200 (valid) or 400 (business rule) — but NOT 403 (forbidden).
        self.assertNotEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


# ═════════════════════════════════════════════════════════════════════════════
# F-05 — Share tokens require course access
# ═════════════════════════════════════════════════════════════════════════════

class ShareTokenEntitlementTests(AuthzTestBase):
    URL = '/api/formation/share-tokens/'

    def test_unenrolled_user_cannot_mint(self):
        self.client.force_authenticate(self.user)
        resp = self.client.post(
            self.URL,
            {'course_id': str(self.paid_course.id), 'visibility': 'token'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_enrolled_user_can_mint(self):
        Enrollment.objects.create(
            user=self.user, course=self.paid_course, status=EnrollmentStatus.ACTIVE,
        )
        self.client.force_authenticate(self.user)
        resp = self.client.post(
            self.URL,
            {'course_id': str(self.paid_course.id), 'visibility': 'token'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_admin_can_mint_without_enrollment(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.post(
            self.URL,
            {'course_id': str(self.paid_course.id), 'visibility': 'token'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)


# ═════════════════════════════════════════════════════════════════════════════
# N-03 — Gift claim keeps Course.students in sync (uses the enroll primitive)
# ═════════════════════════════════════════════════════════════════════════════

class EnrollmentServiceEntitlementTests(TestCase):
    """Service-level checks for the entitlement helper."""

    def setUp(self):
        self.user = User.objects.create_user(email='s@t.com', password='pw', role='USER')
        self.cat = Category.objects.create(name={'en': 'c'}, slug='c')
        self.free = Course.objects.create(
            title='f', slug='f', description='d', category=self.cat,
            status=CourseStatus.PUBLISHED, price=0, is_free=True,
        )
        self.paid = Course.objects.create(
            title='p', slug='p', description='d', category=self.cat,
            status=CourseStatus.PUBLISHED, price=5000, originalPrice=5000,
        )

    def test_has_entitlement_free(self):
        from formation.services.enrollment_service import has_entitlement
        self.assertTrue(has_entitlement(self.user, self.free))

    def test_has_entitlement_paid_without_order(self):
        from formation.services.enrollment_service import has_entitlement
        self.assertFalse(has_entitlement(self.user, self.paid))

    def test_self_enroll_paid_raises(self):
        from formation.services.enrollment_service import self_enroll, PaymentRequired
        with self.assertRaises(PaymentRequired):
            self_enroll(self.user, self.paid)

    def test_self_enroll_paid_after_payment(self):
        from formation.services.enrollment_service import self_enroll
        order = Order.objects.create(user=self.user, status=OrderStatus.PAID, total=5000)
        OrderItem.objects.create(order=order, course=self.paid, price=5000)
        enrollment = self_enroll(self.user, self.paid)
        self.assertEqual(enrollment.status, EnrollmentStatus.ACTIVE)
