"""
Skill vocabulary shared with Oosira (CV builder).

A course's ``skills`` must only contain keywords from
``formation/data/skill_keywords_fr.csv`` (column ``mot_cle``). Oosira computes
a CV's missing skills with the exact same keywords, so a course is
recommended only when one of its tags equals a missing skill — free text
here would silently never match.

The CSV is a copy of ``oosira-backend/data/esco/skill_keywords_fr.csv``;
update both together.
"""

import csv
import os
from functools import lru_cache

from django.core.exceptions import ValidationError

VOCAB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'skill_keywords_fr.csv')
MAX_SKILLS_PER_COURSE = 20


@lru_cache(maxsize=1)
def skill_keywords() -> frozenset:
    with open(VOCAB_FILE, 'r', encoding='utf-8-sig') as f:
        return frozenset(row['mot_cle'] for row in csv.DictReader(f) if row.get('mot_cle'))


def validate_skill_keywords(value):
    """Model-field validator: a list of known, distinct keywords."""
    if not isinstance(value, list):
        raise ValidationError('Skills must be a list of keywords.')
    if len(value) > MAX_SKILLS_PER_COURSE:
        raise ValidationError(f'At most {MAX_SKILLS_PER_COURSE} skills per course.')
    if len(set(value)) != len(value):
        raise ValidationError('Skills must not contain duplicates.')
    vocab = skill_keywords()
    unknown = [s for s in value if not isinstance(s, str) or s not in vocab]
    if unknown:
        raise ValidationError(
            'Unknown skill keyword(s): %(unknown)s. Use keywords from skill_keywords_fr.csv.',
            params={'unknown': ', '.join(map(str, unknown))},
        )
