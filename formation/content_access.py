"""
Who may receive a course's protected lesson content.

Protected content = a lesson's audio file, slide image and slide text, plus a
course's downloadable materials. Course structure (titles, durations, counts)
stays public so the catalogue and course pages can render for everyone.

Rules
-----
* Lessons in a preview section (TEASER, INTRO) are public.
* Free courses are fully public.
* Admins see everything.
* Otherwise the user needs an ACTIVE or COMPLETED enrollment in the course.

Deny by default: a serializer with no request in its context gets the public
view, so a new endpoint can't leak content by forgetting to pass access info.
"""

from formation.models import Enrollment, EnrollmentStatus, SectionType
from formation.services.enrollment_service import course_is_free

PREVIEW_SECTION_TYPES = frozenset({SectionType.TEASER, SectionType.INTRO})

_ACCESS_STATUSES = (EnrollmentStatus.ACTIVE, EnrollmentStatus.COMPLETED)

PROTECTED_LESSON_FIELDS = ('audioUrl', 'diapositiveUrl', 'content')
PROTECTED_MATERIAL_FIELDS = ('file', 'url', 'download_url')


class ContentAccess:
    """The set of courses one requester may read in full."""

    def __init__(self, all_courses=False, course_ids=()):
        self.all_courses = all_courses
        self.course_ids = frozenset(course_ids)

    @property
    def cache_scope(self):
        """
        Name of the shared cache this requester's responses may use, or None.

        Responses are identical for every anonymous/unenrolled user ("public")
        and for every admin ("admin"), so those can share a cache. Anyone with
        enrollments gets a personal response that must never be cached.
        """
        if self.all_courses:
            return 'admin'
        if not self.course_ids:
            return 'public'
        return None

    def allows(self, course):
        return (
            self.all_courses
            or course_is_free(course)
            or course.pk in self.course_ids
        )

    def allows_section(self, section):
        return section.type in PREVIEW_SECTION_TYPES or self.allows(section.course)

    @classmethod
    def for_user(cls, user):
        if not user or not user.is_authenticated:
            return PUBLIC
        if getattr(user, 'is_admin', False):
            return cls(all_courses=True)
        ids = Enrollment.objects.filter(
            user=user, status__in=_ACCESS_STATUSES,
        ).values_list('course_id', flat=True)
        return cls(course_ids=ids)


PUBLIC = ContentAccess()


def access_for_request(request):
    """ContentAccess for a request, computed once and memoized on it."""
    if request is None:
        return PUBLIC
    access = getattr(request, '_ooskills_content_access', None)
    if access is None:
        access = ContentAccess.for_user(getattr(request, 'user', None))
        setattr(request, '_ooskills_content_access', access)
    return access


def access_from_context(context):
    return access_for_request((context or {}).get('request'))
