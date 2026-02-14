"""
Quiz Service — scoring, XP, threshold checking, attempt limiting.

All quiz mutations use atomic transactions to prevent race conditions
on attempt counters.
"""

from decimal import Decimal

from django.db import transaction
from django.db.models import Max

from formation.models import Quiz, QuizAttempt, QuizQuestion, Enrollment


class QuizLimitExceeded(Exception):
    pass


def submit_quiz(
    enrollment: Enrollment,
    quiz: Quiz,
    answers: dict,
) -> QuizAttempt:
    """
    Score a quiz submission and create an attempt record.

    Args:
        enrollment: Active enrollment
        quiz: The quiz being attempted
        answers: dict mapping question_id (str) -> selected_option_index (int)

    Returns:
        QuizAttempt with score, passed, xp_earned, feedback populated.

    Raises:
        QuizLimitExceeded: if max_attempts reached.
    """
    with transaction.atomic():
        # Check attempt limit
        existing_attempts = QuizAttempt.objects.select_for_update().filter(
            enrollment=enrollment, quiz=quiz,
        ).count()

        if quiz.max_attempts > 0 and existing_attempts >= quiz.max_attempts:
            raise QuizLimitExceeded(
                f'Maximum attempts ({quiz.max_attempts}) reached for this quiz.'
            )

        # Fetch questions
        questions = list(quiz.questions.all().order_by('sequence'))
        total = len(questions)
        if total == 0:
            raise ValueError('Quiz has no questions.')

        correct = 0
        feedback = []

        for q in questions:
            q_id = str(q.id)
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
        passed = score >= quiz.pass_threshold
        xp = quiz.xp_reward if passed else 0

        attempt = QuizAttempt.objects.create(
            enrollment=enrollment,
            quiz=quiz,
            score=score,
            answers=answers,
            passed=passed,
            xp_earned=xp,
            feedback=feedback,
            attempt_number=existing_attempts + 1,
        )

    return attempt


def get_remaining_attempts(enrollment: Enrollment, quiz: Quiz) -> int | None:
    """Return remaining attempts, or None if unlimited."""
    if quiz.max_attempts == 0:
        return None
    used = QuizAttempt.objects.filter(enrollment=enrollment, quiz=quiz).count()
    return max(0, quiz.max_attempts - used)


def get_best_score(enrollment: Enrollment, quiz: Quiz) -> float:
    """Return best score achieved across all attempts."""
    result = QuizAttempt.objects.filter(
        enrollment=enrollment, quiz=quiz,
    ).aggregate(best=Max('score'))
    return float(result['best'] or 0)
