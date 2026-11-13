"""The staging demo-course seed (audit K01)."""
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from formation.models import Category, Course, FinalQuiz, Lesson, QuizQuestion


@override_settings(ENVIRONMENT='staging')
class SeedDemoCoursesTests(TestCase):
    def run_cmd(self, *args):
        call_command('seed_demo_courses', *args, stdout=StringIO())

    def test_creates_published_courses_with_quizzes_and_final_exam(self):
        self.run_cmd()
        self.assertEqual(Category.objects.count(), 4)
        courses = Course.objects.filter(slug__startswith='demo-')
        self.assertEqual(courses.count(), 3)
        self.assertTrue(all(c.status == 'published' for c in courses))
        self.assertEqual(courses.filter(is_free=True).count(), 1)
        self.assertEqual(Lesson.objects.count(), 18)
        self.assertEqual(QuizQuestion.objects.count(), 24)
        self.assertEqual(FinalQuiz.objects.count(), 3)
        paid = courses.get(slug='demo-communication-professionnelle')
        self.assertEqual((paid.price, paid.originalPrice), (2500, 3500))

    def test_rerun_keeps_existing_content(self):
        self.run_cmd()
        Course.objects.filter(slug='demo-communication-professionnelle').update(title='Edited in admin')
        self.run_cmd()
        self.assertEqual(Course.objects.filter(slug__startswith='demo-').count(), 3)
        self.assertEqual(Course.objects.get(slug='demo-communication-professionnelle').title, 'Edited in admin')

    def test_delete_removes_demo_courses(self):
        self.run_cmd()
        self.run_cmd('--delete')
        self.assertFalse(Course.objects.filter(slug__startswith='demo-').exists())

    @override_settings(ENVIRONMENT='production')
    def test_refuses_in_production(self):
        with self.assertRaises(CommandError):
            self.run_cmd()
        self.assertFalse(Course.objects.exists())


@override_settings(ENVIRONMENT='staging')
class SeedDemoCoursesApiTests(TestCase):
    def test_catalogue_and_course_page_show_the_demo_courses(self):
        call_command('seed_demo_courses', stdout=StringIO())
        res = self.client.get('/api/formation/courses/')
        self.assertEqual(res.status_code, 200)
        body = res.json()
        rows = body['results'] if isinstance(body, dict) else body
        self.assertEqual({r['slug'] for r in rows} >= {
            'demo-gestion-de-projet-les-bases', 'demo-communication-professionnelle',
            'demo-personal-productivity-basics'}, True)
        cats = self.client.get('/api/formation/categories/')
        self.assertEqual(cats.status_code, 200)
        detail = self.client.get('/api/formation/courses/demo-gestion-de-projet-les-bases/')
        self.assertEqual(detail.status_code, 200, detail.content[:300])
