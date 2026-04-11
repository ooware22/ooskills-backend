import zipfile
import json
import os
import tempfile
import shutil
import threading
import logging
from django.core.files import File
from django.db import connection, close_old_connections
from django.db.utils import OperationalError, InterfaceError
from formation.models import (
    Course, Section, Module, Lesson, SectionType, LessonType, DisplayMode, CourseStatus,
    Quiz, QuizQuestion, FinalQuiz,
)

logger = logging.getLogger(__name__)


def _save_with_db_retry(instance, update_fields=None, retries=1):
    """Retry save once after refreshing stale DB connections."""
    for attempt in range(retries + 1):
        try:
            if update_fields:
                instance.save(update_fields=update_fields)
            else:
                instance.save()
            return
        except (OperationalError, InterfaceError):
            if attempt >= retries:
                raise
            close_old_connections()

def _upload_files_background(temp_dir, should_cleanup, lesson_file_mappings):
    """
    Background worker to upload audio and slides to Supabase/S3.
    """
    from formation.models import Lesson
    try:
        for mapping in lesson_file_mappings:
            try:
                lesson = Lesson.objects.get(id=mapping['lesson_id'])
                if mapping['audio_path'] and os.path.exists(mapping['audio_path']):
                    with open(mapping['audio_path'], 'rb') as af:
                        lesson.audioUrl.save(mapping['audio_name'], File(af), save=False)
                if mapping['bg_path'] and os.path.exists(mapping['bg_path']):
                    with open(mapping['bg_path'], 'rb') as sf:
                        lesson.diapositiveUrl.save(mapping['bg_name'], File(sf), save=False)
                _save_with_db_retry(lesson, update_fields=['audioUrl', 'diapositiveUrl'])
            except Exception as e:
                logger.error(f"Error uploading files for lesson {mapping['lesson_id']}: {e}")
    finally:
        # Cleanup
        if should_cleanup and temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        # Close db connection used by thread
        connection.close()

def normalize_formation(formation):
    """
    Normalizes complex nested formation.json schemas into a flat list of modules or quizzes.
    
    Quiz sub-levels (QUIZ_INIT, QUIZ_APPRO, QUIZ_CAS) are merged into their parent
    content sections (INIT, APPRO, CAS) so quizzes attach to the correct section.
    The main QUIZ (certification) produces a FinalQuiz entry at course level.
    QUIZ_FEEDBACK is stored as metadata, not a separate section.
    """
    if isinstance(formation, dict):
        normalized = []
        # Check for complex dictionary layout, usually mapped from a Master Kaggle structure
        if 'formation' in formation and isinstance(formation['formation'], dict) and 'levels' in formation['formation'] and 'levels' in formation and isinstance(formation['levels'], dict):
            level_ids_raw = formation['formation']['levels']
            levels_dict = formation['levels']

            # Enforce canonical pedagogical ordering (formation.json may be alphabetical)
            LEVEL_ORDER = ['TEASER', 'INTRO', 'INIT', 'APPRO', 'CAS', 'CONCL',
                           'QUIZ', 'QUIZ_INIT', 'QUIZ_APPRO', 'QUIZ_CAS', 'QUIZ_FEEDBACK']
            def _level_sort_key(lvl_id):
                try:
                    return LEVEL_ORDER.index(lvl_id)
                except ValueError:
                    return len(LEVEL_ORDER)  # unknown levels go last
            level_ids = sorted(level_ids_raw, key=_level_sort_key)

            # ── Phase 1: collect section-level quizzes from QUIZ_* sub-levels ──
            section_quizzes = {}  # parent_level -> {questions, title, pass_threshold}
            for lvl_id in level_ids:
                if lvl_id.startswith('QUIZ_') and lvl_id != 'QUIZ_FEEDBACK' and lvl_id in levels_dict:
                    parent_level = lvl_id.replace('QUIZ_', '')
                    quiz_data = levels_dict[lvl_id]
                    questions = quiz_data.get('questions', [])
                    if questions:
                        level_quiz_meta = quiz_data.get('level_quiz', {})
                        section_quizzes[parent_level] = {
                            'questions': questions,
                            'title': level_quiz_meta.get('title', f'Quiz — {parent_level}'),
                            'pass_threshold': level_quiz_meta.get('pass_threshold', 70),
                        }

            # ── Phase 2: process each level ──
            for lvl_id in level_ids:
                if lvl_id not in levels_dict:
                    continue
                lvl_data = levels_dict[lvl_id]

                # Skip quiz sub-levels — they are merged into parent sections
                if lvl_id.startswith('QUIZ_'):
                    continue

                # Handle QUIZ (certification) → emitted as a final_quiz entry
                if lvl_id == 'QUIZ':
                    blocs = lvl_data.get('blocs', [])
                    all_questions = []
                    for bloc in blocs:
                        all_questions.extend(bloc.get('questions', []))
                    if all_questions:
                        cert = lvl_data.get('certification', {})
                        seuils = cert.get('seuils', {})
                        normalized.append({
                            'level': lvl_id,
                            'modules': [],
                            'is_quiz': False,
                            'is_final_quiz': True,
                            'final_quiz_data': {
                                'title': cert.get('title', 'Examen Final'),
                                'questions': all_questions,
                                'pass_threshold': seuils.get('competent', 70),
                                'num_questions': cert.get('total_questions', len(all_questions)),
                            }
                        })
                    continue

                # Normal content level (INTRO, INIT, APPRO, CAS, CONCL)
                normalized_entry = {
                    'level': lvl_id,
                    'modules': [],
                    'is_quiz': False,
                    'is_final_quiz': False,
                }

                if 'chapters' in lvl_data:
                    chapters = lvl_data.get('chapters', [])
                    for ch in chapters:
                        chapter_num = str(ch.get('chapter_num', ch.get('chapter', 0))).zfill(2)
                        ch_title = ch.get('title', f"Chapter {chapter_num}")

                        mapped_slides = []
                        for idx, s in enumerate(ch.get('slides', [])):
                            slide_num = str(s.get('slide_num', idx + 1)).zfill(2)
                            # Infer expected audio and bg paths natively
                            if 'audio' not in s:
                                s['audio'] = f"{lvl_id.lower()}/ch{chapter_num}_s{slide_num}.mp3"
                            if 'bg' not in s:
                                s['bg'] = f"{lvl_id.lower()}/ch{chapter_num}_s{slide_num}.png"

                            s_title = s.get('title', f"Slide {idx + 1}")
                            if 'title' not in s:
                                s['title'] = s_title

                            mapped_slides.append(s)

                        normalized_entry['modules'].append({
                            'title': ch_title,
                            'slides': mapped_slides
                        })

                # Merge quiz from matching QUIZ_* sub-level into this section
                if lvl_id in section_quizzes:
                    sq = section_quizzes[lvl_id]
                    normalized_entry['questions_data'] = sq['questions']
                    normalized_entry['quiz_title'] = sq['title']
                    normalized_entry['quiz_pass_threshold'] = sq['pass_threshold']

                # Backward compat: the level itself may have inline questions
                if 'questions' in lvl_data and 'questions_data' not in normalized_entry:
                    questions = lvl_data.get('questions', [])
                    if questions:
                        normalized_entry['is_quiz'] = True
                        normalized_entry['questions_count'] = len(questions)
                        normalized_entry['questions_data'] = questions

                # Include the entry if it has content or a quiz
                has_content = 'chapters' in lvl_data
                has_quiz = 'questions_data' in normalized_entry
                has_inline_q = 'questions' in lvl_data
                if has_content or has_quiz or has_inline_q:
                    normalized.append(normalized_entry)

            return normalized
        else:
            # Fallback simple dict format
            if 'levels' in formation and isinstance(formation['levels'], list):
                return formation['levels']
            elif 'formation' in formation and isinstance(formation['formation'], dict) and 'levels' in formation['formation']:
                return formation['formation']['levels']
    return formation


def parse_narration_to_script(narration_text):
    if not isinstance(narration_text, str):
        return {"mode": "multi_speaker", "speakers": []}
    
    speakers = []
    lines = narration_text.split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            continue
        parts = line.split('|', 2)
        if len(parts) >= 3:
            speakers.append({
                "speaker": parts[0].strip(),
                "emotion": parts[1].strip(),
                "text": parts[2].strip()
            })
        elif len(parts) == 2:
            speakers.append({
                "speaker": parts[0].strip(),
                "emotion": "",
                "text": parts[1].strip()
            })
        else:
            speakers.append({
                "speaker": "H",
                "emotion": "",
                "text": line
            })
    return {"mode": "multi_speaker", "speakers": speakers}


def _create_quiz_question(quiz_or_final, q, q_idx, is_final=False):
    """
    Parse a quiz question (list or dict format) and create a QuizQuestion.
    
    Supports both Quiz (section-level) and FinalQuiz (course-level).
    For FinalQuiz, questions are stored as QuizQuestion on a temporary Quiz
    linked to the course, since FinalQuiz randomly pulls from section quizzes.
    
    List format: [type, question_text, options, correct_answer, metadata, difficulty]
    Dict format: {question, options/choices, correct_answer, explanation}
    """
    from formation.models import QuizQuestion, QuestionType, QuestionDifficulty

    # ── Parse question data ──
    q_type = QuestionType.MULTIPLE_CHOICE
    difficulty = QuestionDifficulty.EASY

    if isinstance(q, list):
        # Array format: [type_str, text, options, answer, meta_dict, difficulty_str]
        type_str = q[0] if len(q) > 0 else 'mc'
        ques_text = q[1] if len(q) > 1 else f"Question {q_idx+1}"
        options = q[2] if len(q) > 2 else ["A", "B"]
        ans = q[3] if len(q) > 3 else 0
        meta = q[4] if len(q) > 4 else {}
        diff_str = q[5] if len(q) > 5 else 'easy'

        # Convert options dict to list (for match-type questions)
        if isinstance(options, dict):
            options = list(options.values())
        if isinstance(options, bool):
            options = ["Vrai", "Faux"]

        # Build explanation from metadata
        if isinstance(meta, dict):
            parts = []
            if meta.get('why'):
                parts.append(meta['why'])
            if meta.get('trap'):
                parts.append(f"Piège : {meta['trap']}")
            if meta.get('ref'):
                parts.append(f"Réf : {meta['ref']}")
            explanation = ' | '.join(parts)
        else:
            explanation = str(meta) if meta else ''

        # Map type string
        type_map = {
            'mc': QuestionType.MULTIPLE_CHOICE,
            'tf': QuestionType.TRUE_FALSE,
            'sc': QuestionType.SCENARIO,
            'diag': QuestionType.SCENARIO,
            'match': QuestionType.MULTIPLE_CHOICE,
            'gap': QuestionType.MULTIPLE_CHOICE,
            'ord': QuestionType.MULTIPLE_CHOICE,
            'pri': QuestionType.MULTIPLE_CHOICE,
        }
        q_type = type_map.get(type_str, QuestionType.MULTIPLE_CHOICE)

        # Map difficulty
        diff_map = {
            'easy': QuestionDifficulty.EASY,
            'medium': QuestionDifficulty.MEDIUM,
            'hard': QuestionDifficulty.HARD,
            'expert': QuestionDifficulty.EXPERT,
        }
        difficulty = diff_map.get(diff_str, QuestionDifficulty.EASY)

    elif isinstance(q, dict):
        ques_text = q.get('question', f"Question {q_idx+1}")
        options = q.get('options') or q.get('choices') or [
            q.get('option1'), q.get('option2'), q.get('option3'), q.get('option4')
        ]
        options = [o for o in options if o is not None]
        ans = q.get('correct_answer', 0)
        explanation = q.get('explanation', '')
    else:
        return  # Skip unrecognized format

    # Normalize answer
    if isinstance(ans, str) and ans.isdigit():
        ans = int(ans)
    if isinstance(ans, bool):
        ans = 0 if ans else 1

    # Ensure options is a valid list
    if not isinstance(options, list):
        options = ["A", "B"]

    if is_final:
        # For FinalQuiz, we still create QuizQuestion entries but linked
        # to a section quiz. The FinalQuiz model pulls randomly from them.
        # We create them on the quiz passed as quiz_or_final (which is a FinalQuiz).
        # Since FinalQuiz doesn't have a direct questions relation,
        # we skip individual question creation - they're stored in section quizzes
        # and pulled randomly at quiz time.
        return
    
    QuizQuestion.objects.create(
        quiz=quiz_or_final,
        question=ques_text,
        type=q_type,
        options=options or ["A", "B"],
        correct_answer=ans if isinstance(ans, int) else 0,
        explanation=explanation,
        difficulty=difficulty,
        sequence=q_idx + 1,
    )


def parse_zip_plan(zip_file_path):
    """
    Reads the ZIP file and returns a structured plan dictionary 
    for preview before generating the course.
    """
    plan = {
        'title': 'Unknown',
        'expert': 'Unknown',
        'sections_count': 0,
        'lessons_count': 0,
        'quiz_questions_count': 0,
        'final_quiz_questions_count': 0,
        'sections': [],
        'manifest': None,
        'formation': None
    }
    
    with zipfile.ZipFile(zip_file_path, 'r') as z:
        manifest_file = next((name for name in z.namelist() if name.endswith('manifest.json')), None)
        formation_file = next((name for name in z.namelist() if name.endswith('formation.json')), None)
        
        if manifest_file:
            with z.open(manifest_file) as f:
                manifest = json.load(f)
                plan['title'] = manifest.get('title', 'Unknown Title')
                plan['expert'] = manifest.get('expert', 'Unknown')
                plan['manifest'] = manifest
        
        if formation_file:
            with z.open(formation_file) as f:
                formation = json.load(f)
                plan['formation'] = formation
                
                # Normalize formation depending on schema
                formation = normalize_formation(formation)

                if isinstance(formation, list):
                    for sec_idx, module in enumerate(formation):
                        # Final quiz (certification) — not a visible section
                        if module.get('is_final_quiz'):
                            fq = module.get('final_quiz_data', {})
                            plan['final_quiz_questions_count'] = len(fq.get('questions', []))
                            continue

                        plan['sections_count'] += 1
                        # Count lessons from modules
                        total_slides = sum(
                            len(m.get('slides', []))
                            for m in module.get('modules', [])
                        )
                        # Count quiz questions attached to this section
                        quiz_q = len(module.get('questions_data', []))
                        plan['lessons_count'] += total_slides
                        plan['quiz_questions_count'] += quiz_q

                        sec_info = {
                            'title': module.get('level', f"Section {sec_idx+1}"),
                            'lessons_count': total_slides,
                        }
                        if quiz_q:
                            sec_info['quiz_questions'] = quiz_q
                        plan['sections'].append(sec_info)

    return plan


def import_course_from_zip(zip_file_path, category, instructor, temp_dir=None):
    """
    Extracts the ZIP file, creates Course, Sections, and Lessons, 
    and uploads audio and slides to Supabase Storage.
    """
    should_cleanup = False
    if not temp_dir:
        temp_dir = tempfile.mkdtemp(prefix="ooskills_import_")
        should_cleanup = True

    # Import can run after a long upload/parse step; refresh stale pooled connections.
    close_old_connections()
        
    try:
        with zipfile.ZipFile(zip_file_path, 'r') as z:
            z.extractall(temp_dir)
            
        manifest_path = None
        formation_path = None
        base_dir = temp_dir
        
        for root, dirs, files in os.walk(temp_dir):
            if 'manifest.json' in files:
                manifest_path = os.path.join(root, 'manifest.json')
                base_dir = root
            if 'formation.json' in files:
                formation_path = os.path.join(root, 'formation.json')
                if not manifest_path:
                    base_dir = root
        
        manifest = {}
        if manifest_path and os.path.exists(manifest_path):
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
                
        formation = []
        if formation_path and os.path.exists(formation_path):
            with open(formation_path, 'r', encoding='utf-8') as f:
                formation = json.load(f)
                
        # 1. Create Course
        lesson_file_mappings = []
        
        title = manifest.get('title', 'Formation Importée')
        course = Course.objects.create(
            title=title,
            category=category,
            instructor=instructor,
            status=CourseStatus.DRAFT,  # Keep it draft so admin can review
        )
        
        # 2. Parse Modules/Sections
        formation = normalize_formation(formation)

        if isinstance(formation, list):
            section_seq = 0
            for sec_idx, module_data in enumerate(formation):
                level_name = module_data.get('level', f"Module {sec_idx+1}")

                # ── Handle FinalQuiz (certification QUIZ) ────────────────
                if module_data.get('is_final_quiz'):
                    fq_data = module_data.get('final_quiz_data', {})
                    fq_questions = fq_data.get('questions', [])
                    if fq_questions:
                        final_quiz = FinalQuiz.objects.create(
                            course=course,
                            title=fq_data.get('title', 'Examen Final'),
                            num_questions=fq_data.get('num_questions', len(fq_questions)),
                            pass_threshold=fq_data.get('pass_threshold', 70),
                        )
                        for q_idx, q in enumerate(fq_questions):
                            _create_quiz_question(final_quiz, q, q_idx, is_final=True)
                        logger.info(f"Created FinalQuiz with {len(fq_questions)} questions")
                    continue

                # ── Create Section for content levels ────────────────────
                is_quiz = module_data.get('is_quiz', False)
                section_seq += 1
                
                # Try to map level_name to SectionType, fallback to APPRO
                sec_type = SectionType.APPRO
                level_lower = level_name.lower()
                if "teaser" in level_lower:
                    sec_type = SectionType.TEASER
                elif "intro" in level_lower:
                    sec_type = SectionType.INTRO
                elif "init" in level_lower:
                    sec_type = SectionType.INIT
                elif "appro" in level_lower:
                    sec_type = SectionType.APPRO
                elif "cas" in level_lower or "etude" in level_lower:
                    sec_type = SectionType.CAS
                elif "concl" in level_lower:
                    sec_type = SectionType.CONCL
                
                section = Section.objects.create(
                    course=course,
                    title=level_name,
                    type=sec_type,
                    sequence=section_seq
                )
                
                # ── Create modules/lessons ───────────────────────────────
                modules_data = module_data.get('modules', [])
                for mod_idx, m_data in enumerate(modules_data):
                    mod_title = m_data.get('title', f"Module {mod_idx+1}")
                    module_obj = Module.objects.create(
                        section=section,
                        title=mod_title,
                        sequence=mod_idx + 1
                    )

                    slides = m_data.get('slides', [])
                    for slide_idx, slide_data in enumerate(slides):
                        lesson_title = slide_data.get('title', f"{mod_title} - Slide {slide_idx+1}")

                        duration_seconds = slide_data.get('duration_seconds') or slide_data.get('duration', 0)
                        if isinstance(duration_seconds, str) and duration_seconds.isdigit():
                            duration_seconds = int(duration_seconds)
                        elif not isinstance(duration_seconds, int):
                            duration_seconds = 0

                        slide_type_val = slide_data.get('slide_type', 'bullet_points')
                        display_mode_val = slide_data.get('display_mode', DisplayMode.BOTH)

                        # Normalize: parse narration string and visuals
                        if 'narration' in slide_data and isinstance(slide_data['narration'], str):
                            slide_data['narration_script'] = parse_narration_to_script(slide_data['narration'])
                        if 'visuals' in slide_data and 'visual_content' not in slide_data:
                            slide_data['visual_content'] = slide_data['visuals']

                        lesson = Lesson(
                            module=module_obj,
                            title=lesson_title[:300],
                            type=LessonType.SLIDE,
                            sequence=slide_idx + 1,
                            duration_seconds=duration_seconds,
                            slide_type=slide_type_val,
                            display_mode=display_mode_val,
                            content=slide_data,
                        )

                        audio_filename = slide_data.get('audio')
                        slide_bg = slide_data.get('bg')
                        audio_path_final = None
                        bg_path_final = None

                        if audio_filename:
                            ap = os.path.join(base_dir, 'audio', audio_filename)
                            if os.path.exists(ap):
                                audio_path_final = ap

                        if slide_bg:
                            bp = os.path.join(base_dir, 'slides', slide_bg)
                            if not os.path.exists(bp):
                                level_dir = slide_bg.split('/')[0] if '/' in slide_bg else ''
                                ext = slide_bg.split('.')[-1] if '.' in slide_bg else 'png'
                                fallback_name = f"slide_{str(slide_idx + 1).zfill(2)}.{ext}"
                                fallback_path = os.path.join(base_dir, 'slides', level_dir, fallback_name)
                                if os.path.exists(fallback_path):
                                    bp = fallback_path
                                    slide_bg = f"{level_dir}/{fallback_name}" if level_dir else fallback_name
                            if os.path.exists(bp):
                                bg_path_final = bp

                        _save_with_db_retry(lesson)

                        if audio_path_final or bg_path_final:
                            lesson_file_mappings.append({
                                'lesson_id': lesson.id,
                                'audio_path': audio_path_final,
                                'audio_name': os.path.basename(audio_filename) if audio_filename else None,
                                'bg_path': bg_path_final,
                                'bg_name': os.path.basename(slide_bg) if slide_bg else None,
                            })

                # ── Attach section quiz if questions exist ────────────────
                questions_data = module_data.get('questions_data', [])
                if questions_data:
                    quiz_title = module_data.get('quiz_title', f"Quiz — {level_name}")
                    quiz_threshold = module_data.get('quiz_pass_threshold', 70)
                    quiz = Quiz.objects.create(
                        section=section,
                        title=quiz_title,
                        pass_threshold=quiz_threshold
                    )
                    for q_idx, q in enumerate(questions_data):
                        _create_quiz_question(quiz, q, q_idx, is_final=False)
                    logger.info(f"Attached quiz '{quiz_title}' ({len(questions_data)} questions) to section '{level_name}'")
                    
        # Start background thread to upload files
        thread = threading.Thread(
            target=_upload_files_background,
            args=(temp_dir, should_cleanup, lesson_file_mappings)
        )
        thread.start()
        return course
        
    except Exception as e:
        if should_cleanup and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        raise e


def _start_upload_thread(temp_dir, should_cleanup, lesson_file_mappings):
    thread = threading.Thread(
        target=_upload_files_background,
        args=(temp_dir, should_cleanup, lesson_file_mappings),
    )
    thread.daemon = True
    thread.start()
