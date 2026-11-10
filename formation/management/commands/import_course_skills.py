"""
Load course skill tags from a CSV.

Usage:
    python manage.py import_course_skills course_skills.csv --dry-run
    python manage.py import_course_skills course_skills.csv

Required columns: ``course_slug`` and ``skills`` (a JSON array of keywords from
formation/data/skill_keywords_fr.csv). Other columns are ignored, so the file
written by ``export_course_skills`` can be edited and loaded back as-is.

All rows are validated first; if any slug or keyword is unknown nothing is
saved. Re-running with the same file is a no-op.
"""

import csv
import json

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from formation.models import Course
from formation.skills_vocab import validate_skill_keywords


class Command(BaseCommand):
    help = 'Set Course.skills from a CSV (course_slug, skills JSON array)'

    def add_arguments(self, parser):
        parser.add_argument('path', type=str, help='CSV file to read')
        parser.add_argument('--dry-run', action='store_true', help='Validate and report without saving')

    def handle(self, *args, **options):
        with open(options['path'], 'r', encoding='utf-8-sig') as f:
            rows = list(csv.DictReader(f))
        if rows and not {'course_slug', 'skills'} <= set(rows[0]):
            raise CommandError('CSV must have the columns course_slug and skills.')

        courses = Course.objects.in_bulk([r['course_slug'].strip() for r in rows], field_name='slug')
        errors, updates = [], []
        for line, row in enumerate(rows, start=2):
            slug = row['course_slug'].strip()
            course = courses.get(slug)
            if course is None:
                errors.append(f'line {line}: unknown course slug "{slug}"')
                continue
            try:
                skills = json.loads(row['skills'] or '[]')
                validate_skill_keywords(skills)
            except json.JSONDecodeError:
                errors.append(f'line {line} ({slug}): skills is not a JSON array')
                continue
            except ValidationError as e:
                errors.append(f'line {line} ({slug}): {"; ".join(e.messages)}')
                continue
            if skills != course.skills:
                updates.append((course, skills))

        if errors:
            for err in errors:
                self.stderr.write(err)
            raise CommandError(f'{len(errors)} invalid row(s); nothing was saved.')

        if options['dry_run']:
            self.stdout.write(f'Dry run: {len(updates)} of {len(rows)} courses would change.')
            return

        # Course post_save (formation/signals.py) busts the list/detail/catalog caches.
        with transaction.atomic():
            for course, skills in updates:
                course.skills = skills
                course.save(update_fields=['skills', 'updated_at'])

        self.stdout.write(self.style.SUCCESS(f'Updated {len(updates)} of {len(rows)} courses.'))
