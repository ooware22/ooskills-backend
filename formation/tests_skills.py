"""
Course skill tags — the OoSkills half of the Oosira gap-analysis bridge.

Covers: vocabulary validation, the ?skills= filter, the lean catalog
endpoint, admin writes, and the import_course_skills command.
"""

import csv
import json
import os
import tempfile

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from formation.models import Course, CourseStatus
from formation.skills_vocab import skill_keywords, validate_skill_keywords
from users.models import User

CATALOG_URL = '/api/formation/courses/catalog/'
LIST_URL = '/api/formation/courses/'


class SkillVocabularyTests(TestCase):

    def test_vocabulary_is_loaded(self):
        vocab = skill_keywords()
        self.assertGreater(len(vocab), 1000)
        self.assertIn('Python', vocab)
        self.assertIn('Gestion de projets', vocab)

    def test_known_keywords_pass(self):
        validate_skill_keywords(['Python', 'Gestion de projets'])
        validate_skill_keywords([])

    def test_rejects_unknown_keyword(self):
        with self.assertRaises(ValidationError):
            validate_skill_keywords(['Python', 'Not a real skill'])

    def test_rejects_duplicates_and_non_lists(self):
        with self.assertRaises(ValidationError):
            validate_skill_keywords(['Python', 'Python'])
        with self.assertRaises(ValidationError):
            validate_skill_keywords('Python')

    def test_model_full_clean_runs_the_validator(self):
        course = Course(title='Bad', slug='bad', skills=['Not a real skill'])
        with self.assertRaises(ValidationError) as ctx:
            course.full_clean()
        self.assertIn('skills', ctx.exception.message_dict)


@override_settings(CACHES={'default': {
    'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    'LOCATION': 'ooskills-tests-skills',
}})
class CourseSkillsApiTests(TestCase):

    def setUp(self):
        # List/catalog responses are cached; a private LocMem cache keeps clear() from touching Redis.
        cache.clear()
        self.client = APIClient()
        self.python = Course.objects.create(
            title='Python', slug='python-course', status=CourseStatus.PUBLISHED,
            skills=['Python', 'Programmation informatique'],
        )
        self.pm = Course.objects.create(
            title='Gestion de projet', slug='pm-course', status=CourseStatus.PUBLISHED,
            skills=['Gestion de projets', 'Méthodologie Agile'],
        )
        self.draft = Course.objects.create(
            title='Draft', slug='draft-course', status=CourseStatus.DRAFT,
            skills=['Python'],
        )

    def test_catalog_lists_published_courses_with_skills(self):
        resp = self.client.get(CATALOG_URL)
        self.assertEqual(resp.status_code, 200)
        by_slug = {c['slug']: c for c in resp.data}
        self.assertEqual(set(by_slug), {'python-course', 'pm-course'})
        self.assertEqual(by_slug['pm-course']['skills'], ['Gestion de projets', 'Méthodologie Agile'])
        self.assertNotIn('sections', by_slug['pm-course'])

    def test_catalog_hides_drafts_even_from_admins(self):
        admin = User.objects.create_user(email='a@test.com', password='x', role='ADMIN', is_staff=True)
        self.client.force_authenticate(admin)
        slugs = {c['slug'] for c in self.client.get(CATALOG_URL).data}
        self.assertNotIn('draft-course', slugs)

    def test_list_filter_matches_any_keyword(self):
        resp = self.client.get(LIST_URL, {'skills': 'Python,Méthodologie Agile'})
        self.assertEqual(resp.status_code, 200)
        slugs = {c['slug'] for c in resp.data['results']}
        self.assertEqual(slugs, {'python-course', 'pm-course'})

        resp = self.client.get(LIST_URL, {'skills': 'Méthodologie Agile'})
        self.assertEqual({c['slug'] for c in resp.data['results']}, {'pm-course'})

    def test_detail_exposes_skills(self):
        resp = self.client.get(f'{LIST_URL}python-course/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['skills'], ['Python', 'Programmation informatique'])

    def test_admin_write_rejects_unknown_keyword(self):
        admin = User.objects.create_user(email='b@test.com', password='x', role='ADMIN', is_staff=True)
        self.client.force_authenticate(admin)
        resp = self.client.patch(f'{LIST_URL}python-course/', {'skills': ['Not a real skill']}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('skills', resp.data)

        resp = self.client.patch(f'{LIST_URL}python-course/', {'skills': ['Java']}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.python.refresh_from_db()
        self.assertEqual(self.python.skills, ['Java'])


class ImportCourseSkillsCommandTests(TestCase):

    def setUp(self):
        self.course = Course.objects.create(title='Python', slug='python-course', status=CourseStatus.PUBLISHED)
        self.tmpdir = tempfile.mkdtemp()

    def _csv(self, rows):
        path = os.path.join(self.tmpdir, 'skills.csv')
        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(['course_slug', 'skills'])
            for slug, skills in rows:
                writer.writerow([slug, json.dumps(skills, ensure_ascii=False)])
        return path

    def test_imports_valid_rows(self):
        call_command('import_course_skills', self._csv([('python-course', ['Python', 'Débogage'])]))
        self.course.refresh_from_db()
        self.assertEqual(self.course.skills, ['Python', 'Débogage'])

    def test_dry_run_saves_nothing(self):
        call_command('import_course_skills', self._csv([('python-course', ['Python'])]), dry_run=True)
        self.course.refresh_from_db()
        self.assertEqual(self.course.skills, [])

    def test_any_invalid_row_aborts_everything(self):
        path = self._csv([('python-course', ['Python']), ('missing-course', ['Python'])])
        with self.assertRaises(CommandError):
            call_command('import_course_skills', path)
        self.course.refresh_from_db()
        self.assertEqual(self.course.skills, [])

        with self.assertRaises(CommandError):
            call_command('import_course_skills', self._csv([('python-course', ['Not a real skill'])]))

    def test_export_then_import_round_trip(self):
        self.course.skills = ['Python']
        self.course.save()
        path = os.path.join(self.tmpdir, 'export.csv')
        call_command('export_course_skills', path)
        call_command('import_course_skills', path)
        self.course.refresh_from_db()
        self.assertEqual(self.course.skills, ['Python'])
