"""
Final Quiz Service — generates and scores the course-level final exam.

Pulls random questions from all section quizzes in the course,
scores them, and triggers certificate + PDF generation on pass.
"""

import random
from decimal import Decimal

from django.db import transaction

from formation.models import (
    Enrollment, EnrollmentStatus, FinalQuiz, FinalQuizAttempt,
    QuizQuestion,
)
from formation.services.certificate_service import (
    issue_certificate, CertificateAlreadyIssued,
)


class FinalQuizNotConfigured(Exception):
    pass


class FinalQuizLimitExceeded(Exception):
    pass


class CourseNotCompleted(Exception):
    pass


def generate_final_quiz_questions(enrollment: Enrollment) -> list[dict]:
    """
    Generate a random set of questions for the final quiz.

    Pulls from all QuizQuestions across all section quizzes
    of the enrolled course.

    Args:
        enrollment: Must be COMPLETED status (all lessons done).

    Returns:
        List of question dicts (without correct_answer) for the frontend.

    Raises:
        CourseNotCompleted: If enrollment is not completed.
        FinalQuizNotConfigured: If no FinalQuiz exists for the course.
    """
    if enrollment.status != EnrollmentStatus.COMPLETED:
        raise CourseNotCompleted(
            'You must complete all lessons before taking the final quiz.'
        )

    try:
        final_quiz = FinalQuiz.objects.get(course=enrollment.course)
    except FinalQuiz.DoesNotExist:
        raise FinalQuizNotConfigured(
            'No final quiz is configured for this course.'
        )

    # Check attempt limit
    existing_attempts = FinalQuizAttempt.objects.filter(
        enrollment=enrollment, final_quiz=final_quiz,
    ).count()

    if final_quiz.max_attempts > 0 and existing_attempts >= final_quiz.max_attempts:
        raise FinalQuizLimitExceeded(
            f'Maximum attempts ({final_quiz.max_attempts}) reached for the final quiz.'
        )

    # Gather all questions from section quizzes
    all_questions = list(
        QuizQuestion.objects.filter(
            quiz__section__course=enrollment.course,
        ).order_by('?')  # random ordering
    )

    # Sample the configured number (or all if fewer available)
    num = min(final_quiz.num_questions, len(all_questions))
    if num == 0:
        raise ValueError('No questions available for the final quiz.')

    selected = random.sample(all_questions, num)

    # Return serialized questions (without correct_answer)
    return [
        {
            'id': str(q.id),
            'type': q.type,
            'question': q.question,
            'options': q.options,
            'difficulty': q.difficulty,
            'category': q.category,
        }
        for q in selected
    ]


def submit_final_quiz(
    enrollment: Enrollment,
    answers: dict,
    question_ids: list[str],
) -> FinalQuizAttempt:
    """
    Score the final quiz and create an attempt record.

    If the student passes, auto-issue a certificate with PDF.

    Args:
        enrollment: Active/completed enrollment.
        answers: Dict mapping question_id (str) -> selected_option_index (int).
        question_ids: List of question IDs that were presented to the student.

    Returns:
        FinalQuizAttempt with score, passed, feedback populated.

    Raises:
        FinalQuizNotConfigured: If no FinalQuiz for the course.
        FinalQuizLimitExceeded: If max attempts reached.
    """
    try:
        final_quiz = FinalQuiz.objects.get(course=enrollment.course)
    except FinalQuiz.DoesNotExist:
        raise FinalQuizNotConfigured(
            'No final quiz is configured for this course.'
        )

    with transaction.atomic():
        existing_attempts = FinalQuizAttempt.objects.select_for_update().filter(
            enrollment=enrollment, final_quiz=final_quiz,
        ).count()

        if final_quiz.max_attempts > 0 and existing_attempts >= final_quiz.max_attempts:
            raise FinalQuizLimitExceeded(
                f'Maximum attempts ({final_quiz.max_attempts}) reached for the final quiz.'
            )

        # Fetch only the specific questions that were presented
        questions = {
            str(q.id): q
            for q in QuizQuestion.objects.filter(id__in=question_ids)
        }

        total = len(question_ids)
        if total == 0:
            raise ValueError('No questions provided.')

        correct = 0
        feedback = []

        for q_id in question_ids:
            q = questions.get(q_id)
            if q is None:
                continue

            selected = answers.get(q_id)
            is_correct = selected is not None and int(selected) == q.correct_answer

            if is_correct:
                correct += 1

            feedback.append({
                'question_id': q_id,
                'selected': selected,
                'correct_answer': q.correct_answer,
                'is_correct': is_correct,
                'explanation': q.explanation,
            })

        score = Decimal(correct * 100 / total).quantize(Decimal('0.01'))
        passed = score >= final_quiz.pass_threshold
        xp = final_quiz.xp_reward if passed else 0

        attempt = FinalQuizAttempt.objects.create(
            enrollment=enrollment,
            final_quiz=final_quiz,
            score=score,
            answers=answers,
            questions_snapshot=question_ids,
            passed=passed,
            xp_earned=xp,
            feedback=feedback,
            attempt_number=existing_attempts + 1,
        )

    # Auto-issue certificate on pass
    if passed:
        try:
            issue_certificate(enrollment, score=float(score))
        except CertificateAlreadyIssued:
            pass  # already has a certificate

    return attempt


def get_final_quiz_remaining_attempts(
    enrollment: Enrollment,
    final_quiz: FinalQuiz,
) -> int | None:
    """Return remaining attempts, or None if unlimited."""
    if final_quiz.max_attempts == 0:
        return None
    used = FinalQuizAttempt.objects.filter(
        enrollment=enrollment, final_quiz=final_quiz,
    ).count()
    return max(0, final_quiz.max_attempts - used)
