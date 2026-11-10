"""
Paid lesson content (audio, slides, slide text) and course materials must only
reach people allowed to see them. Course structure stays public.

Reported issue: GET /api/formation/courses/<slug>/ returned, without login,
the mp3 + slide links of every lesson (~100 per course), not only the preview.
"""

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from formation.models import (
    Category, Course, CourseMaterial, CourseStatus, Enrollment, EnrollmentStatus,
    Lesson, Module, Section, SectionType,
)
from users.models import User

PAID_LESSONS = 6


def lessons_in(payload):
    """Every lesson dict nested anywhere in an API payload."""
    found = []
    if isinstance(payload, dict):
        if 'diapositiveUrl' in payload and 'title' in payload:
            found.append(payload)
        for v in payload.values():
            found += lessons_in(v)
    elif isinstance(payload, list):
        for v in payload:
            found += lessons_in(v)
    return found


def exposed(lessons):
    return [l for l in lessons if l.get('audioUrl') or l.get('diapositiveUrl') or l.get('content')]


class ContentAccessTests(TestCase):

    def setUp(self):
        cache.clear()
        self.anon = APIClient()
        self.cat = Category.objects.create(name={'en': 'c'}, slug='c')
        self.course = self._course('paid-course', price=5000)
        self.free_course = self._course('free-course', price=0, is_free=True)

        self.student = User.objects.create_user(email='s@t.com', password='pw', role='USER')
        self.admin = User.objects.create_user(
            email='a@t.com', password='pw', role='ADMIN', is_staff=True,
        )

    def _course(self, slug, **kw):
        course = Course.objects.create(
            title=slug, slug=slug, description='d', category=self.cat,
            status=CourseStatus.PUBLISHED, originalPrice=kw.get('price', 0), **kw,
        )
        layout = [(SectionType.TEASER, 1), (SectionType.INTRO, 2), (SectionType.APPRO, PAID_LESSONS)]
        for seq, (stype, n) in enumerate(layout, start=1):
            section = Section.objects.create(course=course, title=stype, type=stype, sequence=seq)
            module = Module.objects.create(section=section, title='m', sequence=1)
            for i in range(n):
                Lesson.objects.create(
                    module=module, title=f'{stype}-{i}', sequence=i,
                    audioUrl=f'{course.id}/{stype}-{i}.mp3',
                    diapositiveUrl=f'{course.id}/{stype}-{i}.webp',
                    content={'en': f'slide text {stype}-{i}'},
                )
        CourseMaterial.objects.create(course=course, name='Workbook', type='pdf', url='https://x/wb.pdf')
        return course

    def _client(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def _enroll(self, status=EnrollmentStatus.ACTIVE):
        Enrollment.objects.create(user=self.student, course=self.course, status=status)

    def _detail(self, client, course=None):
        resp = client.get(f'/api/formation/courses/{(course or self.course).slug}/')
        self.assertEqual(resp.status_code, 200)
        return resp.data

    def _assert_only_preview_exposed(self, payload):
        lessons = lessons_in(payload)
        self.assertEqual(len(lessons), 3 + PAID_LESSONS, 'course outline must stay complete')
        open_titles = {l['title'] for l in exposed(lessons)}
        self.assertEqual(open_titles, {'TEASER-0', 'INTRO-0', 'INTRO-1'})

    def _assert_all_exposed(self, payload):
        lessons = lessons_in(payload)
        self.assertEqual(len(exposed(lessons)), 3 + PAID_LESSONS)

    # ── the reported leak ────────────────────────────────────────────────────

    def test_anonymous_course_detail_exposes_only_preview_lessons(self):
        data = self._detail(self.anon)
        self._assert_only_preview_exposed(data)
        self.assertEqual(data['materials'][0]['name'], 'Workbook')
        self.assertIsNone(data['materials'][0]['url'])

    def test_anonymous_sections_and_modules_are_also_protected(self):
        sections = self.anon.get(f'/api/formation/sections/?course={self.course.slug}')
        self._assert_only_preview_exposed(sections.data)
        modules = self.anon.get('/api/formation/modules/')
        paid = [l for l in lessons_in(modules.data) if l['title'].startswith('APPRO')]
        self.assertEqual(len(paid), PAID_LESSONS * 2)  # both courses
        self.assertEqual(
            [l for l in exposed(paid) if str(self.course.id) in str(l.get('audioUrl'))], [],
        )

    def test_anonymous_material_links_hidden_everywhere(self):
        listing = self.anon.get('/api/formation/courses/').data
        rows = listing.get('results', listing)
        paid = next(r for r in rows if r['slug'] == self.course.slug)
        self.assertIsNone(paid['materials'][0]['url'])
        mats = self.anon.get(f'/api/formation/course-materials/?course={self.course.id}').data
        mats = mats.get('results', mats)
        self.assertIsNone(mats[0]['url'])

    # ── who is allowed ───────────────────────────────────────────────────────

    def test_logged_in_but_not_enrolled_is_protected(self):
        self._assert_only_preview_exposed(self._detail(self._client(self.student)))

    def test_active_enrollment_gets_everything(self):
        self._enroll()
        data = self._detail(self._client(self.student))
        self._assert_all_exposed(data)
        self.assertEqual(data['materials'][0]['url'], 'https://x/wb.pdf')

    def test_completed_enrollment_gets_everything(self):
        self._enroll(EnrollmentStatus.COMPLETED)
        self._assert_all_exposed(self._detail(self._client(self.student)))

    def test_cancelled_enrollment_is_protected(self):
        self._enroll(EnrollmentStatus.CANCELLED)
        self._assert_only_preview_exposed(self._detail(self._client(self.student)))

    def test_admin_gets_everything(self):
        self._assert_all_exposed(self._detail(self._client(self.admin)))
        sections = self._client(self.admin).get(f'/api/formation/sections/?course={self.course.slug}')
        self._assert_all_exposed(sections.data)

    def test_free_course_is_fully_public(self):
        self._assert_all_exposed(self._detail(self.anon, self.free_course))

    # ── the shared cache must not leak in either direction ──────────────────

    def test_cached_public_response_is_not_served_to_enrolled_user(self):
        self._detail(self.anon)  # fills the public cache
        self._enroll()
        self._assert_all_exposed(self._detail(self._client(self.student)))

    def test_enrolled_response_is_never_cached_for_anonymous(self):
        self._enroll()
        self._detail(self._client(self.student))  # personal response
        self._assert_only_preview_exposed(self._detail(self.anon))
        sections_url = f'/api/formation/sections/?course={self.course.slug}'
        self._client(self.student).get(sections_url)
        self._assert_only_preview_exposed(self.anon.get(sections_url).data)

    def test_admin_cache_is_not_served_to_anonymous(self):
        self._detail(self._client(self.admin))
        self._assert_only_preview_exposed(self._detail(self.anon))
