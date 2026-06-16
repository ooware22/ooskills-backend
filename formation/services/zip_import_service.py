import zipfile
import json
import os
import tempfile
import shutil
import threading
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from django.core.files import File
from django.db import connection, close_old_connections
from django.db.utils import OperationalError, InterfaceError
from formation.models import (
    Course, Section, Module, Lesson, SectionType, LessonType, DisplayMode, CourseStatus,
    Quiz, QuizQuestion, FinalQuiz, QuestionType, QuestionDifficulty,
)

logger = logging.getLogger(__name__)
BULK_CREATE_BATCH_SIZE = 200

# All accepted media extensions for ZIP import resolution
AUDIO_EXTENSIONS = [
    'mp3', 'wav', 'ogg', 'flac', 'aac', 'm4a', 'wma',
    'opus', 'webm', 'amr', 'mid', 'midi',
]
SLIDE_EXTENSIONS = [
    'webp', 'png', 'jpg', 'jpeg', 'gif', 'bmp', 'tiff', 'tif',
    'svg', 'avif', 'heic', 'heif', 'ico',
    'mp4', 'webm', 'mov', 'avi', 'mkv', 'ogv',
]


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


def _bulk_create_with_db_retry(model_cls, instances, batch_size=BULK_CREATE_BATCH_SIZE, retries=1):
    """Retry bulk_create once after refreshing stale DB connections."""
    if not instances:
        return instances

    for attempt in range(retries + 1):
        try:
            model_cls.objects.bulk_create(instances, batch_size=batch_size)
            return instances
        except (OperationalError, InterfaceError):
            if attempt >= retries:
                raise
            close_old_connections()

def _upload_single_file(lesson_id, field_name, file_path, file_display_name):
    """
    Upload a single file (audio or slide) to Supabase Storage for a lesson.

    The flow is:
      1. Read file from disk (+ compress images)
      2. Upload to Supabase Storage via the Django FileField (fires background HTTP)
      3. Save the lesson row — uses a fresh DB connection to avoid pool exhaustion
      4. Immediately close the DB connection so the pooler slot is freed

    Returns (lesson_id, field_name, success_bool).
    """
    from formation.models import Lesson
    from formation.storage import compress_image_bytes
    import io
    import time

    MAX_DB_RETRIES = 3

    try:
        with open(file_path, 'rb') as f:
            file_bytes = f.read()

        # Compress slide images before uploading (saves bandwidth + storage)
        if field_name == 'diapositiveUrl':
            file_bytes, file_display_name, _ = compress_image_bytes(
                file_bytes, file_display_name
            )

        # Build an in-memory Django File
        buf = io.BytesIO(file_bytes)
        buf.name = file_display_name
        django_file = File(buf)

        # DB save with retry — each attempt gets a fresh connection
        for attempt in range(MAX_DB_RETRIES):
            try:
                close_old_connections()
                lesson = Lesson.objects.get(id=lesson_id)
                getattr(lesson, field_name).save(file_display_name, django_file, save=False)
                lesson.save(update_fields=[field_name])
                break  # success
            except (OperationalError, InterfaceError) as db_err:
                connection.close()
                if attempt >= MAX_DB_RETRIES - 1:
                    raise db_err
                wait = 3 * (attempt + 1)
                logger.warning(
                    "DB save retry %d/%d for lesson %s field %s (waiting %ds): %s",
                    attempt + 1, MAX_DB_RETRIES, lesson_id, field_name, wait, db_err,
                )
                time.sleep(wait)
        else:
            raise RuntimeError("DB save exhausted retries")

        return (lesson_id, field_name, True)

    except Exception as e:
        logger.error("Upload failed for lesson %s field %s: %s", lesson_id, field_name, e)
        return (lesson_id, field_name, False)
    finally:
        # Always release the DB connection back to the pool immediately
        try:
            connection.close()
        except Exception:
            pass


def _upload_files_background(temp_dir, should_cleanup, lesson_file_mappings):
    """
    Background worker to upload audio and slides to Supabase Storage.

    Uses only 2 concurrent workers to stay within the Supabase free-tier
    connection pooler limit (~10 connections).  Each worker releases its
    DB connection immediately after saving.
    """
    MAX_WORKERS = 2
    try:
        close_old_connections()

        # Build list of (lesson_id, field_name, file_path, display_name) tasks
        upload_tasks = []
        for mapping in lesson_file_mappings:
            lesson_id = mapping.get('lesson_id')
            if not lesson_id:
                continue
            if mapping['audio_path'] and os.path.exists(mapping['audio_path']):
                upload_tasks.append(
                    (lesson_id, 'audioUrl', mapping['audio_path'], mapping['audio_name'])
                )
            if mapping['bg_path'] and os.path.exists(mapping['bg_path']):
                upload_tasks.append(
                    (lesson_id, 'diapositiveUrl', mapping['bg_path'], mapping['bg_name'])
                )

        if not upload_tasks:
            logger.info("No files to upload from ZIP import")
            return

        total = len(upload_tasks)
        logger.info("ZIP import: starting %d file uploads with %d workers", total, MAX_WORKERS)

        done_count = 0
        fail_count = 0

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(_upload_single_file, *task): task
                for task in upload_tasks
            }
            for future in as_completed(futures):
                lesson_id, field_name, success = future.result()
                done_count += 1
                if not success:
                    fail_count += 1
                # Log progress every 5 files
                if done_count % 5 == 0 or done_count == total:
                    logger.info(
                        "ZIP import upload progress: %d/%d done (%d failed)",
                        done_count, total, fail_count,
                    )

        logger.info(
            "ZIP import: all uploads complete — %d/%d succeeded",
            total - fail_count, total,
        )
    finally:
        # Cleanup temp directory
        if should_cleanup and temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        # Close db connection used by this thread
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
                    # Track slide index across ALL chapters in this level
                    # (WEB-format ZIPs use flat slide_01..slide_NN naming)
                    global_slide_idx = 0
                    for ch in chapters:
                        chapter_num = str(ch.get('chapter_num', ch.get('chapter', 0))).zfill(2)
                        ch_title = ch.get('title', f"Chapter {chapter_num}")

                        mapped_slides = []
                        for idx, s in enumerate(ch.get('slides', [])):
                            slide_num = str(s.get('slide_num', idx + 1)).zfill(2)
                            global_slide_idx += 1
                            # Infer expected audio path (chapter-based naming)
                            if 'audio' not in s:
                                s['audio'] = f"{lvl_id.lower()}/ch{chapter_num}_s{slide_num}.mp3"
                            # Infer expected slide bg path
                            # Primary: flat sequential naming with .webp (WEB format)
                            # Fallback: chapter-based naming with .png (legacy format)
                            if 'bg' not in s:
                                s['bg'] = f"{lvl_id.lower()}/slide_{str(global_slide_idx).zfill(2)}.webp"
                                s['bg_fallback'] = f"{lvl_id.lower()}/ch{chapter_num}_s{slide_num}.png"

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


def _parse_quiz_question_payload(q, q_idx):
    """Parse raw question payload into QuizQuestion model fields."""
    q_type = QuestionType.MULTIPLE_CHOICE
    difficulty = QuestionDifficulty.EASY

    if isinstance(q, list):
        type_str = q[0] if len(q) > 0 else 'mc'
        ques_text = q[1] if len(q) > 1 else f"Question {q_idx + 1}"
        options = q[2] if len(q) > 2 else ["A", "B"]
        ans = q[3] if len(q) > 3 else 0
        meta = q[4] if len(q) > 4 else {}
        diff_str = q[5] if len(q) > 5 else 'easy'

        if isinstance(options, dict):
            options = list(options.values())
        if isinstance(options, bool):
            options = ["Vrai", "Faux"]

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

        diff_map = {
            'easy': QuestionDifficulty.EASY,
            'medium': QuestionDifficulty.MEDIUM,
            'hard': QuestionDifficulty.HARD,
            'expert': QuestionDifficulty.EXPERT,
        }
        difficulty = diff_map.get(diff_str, QuestionDifficulty.EASY)

    elif isinstance(q, dict):
        ques_text = q.get('question', f"Question {q_idx + 1}")
        options = q.get('options') or q.get('choices') or [
            q.get('option1'), q.get('option2'), q.get('option3'), q.get('option4')
        ]
        options = [o for o in options if o is not None]
        ans = q.get('correct_answer', 0)
        explanation = q.get('explanation', '')
    else:
        return None

    if isinstance(ans, str) and ans.isdigit():
        ans = int(ans)
    if isinstance(ans, bool):
        ans = 0 if ans else 1

    if not isinstance(options, list):
        options = ["A", "B"]

    return {
        'question': ques_text,
        'type': q_type,
        'options': options or ["A", "B"],
        'correct_answer': ans if isinstance(ans, int) else 0,
        'explanation': explanation,
        'difficulty': difficulty,
        'sequence': q_idx + 1,
    }


def _create_quiz_question(quiz_or_final, q, q_idx, is_final=False):
    """Create one quiz question (kept for compatibility with existing callers)."""
    if is_final:
        return

    payload = _parse_quiz_question_payload(q, q_idx)
    if not payload:
        return

    QuizQuestion.objects.create(quiz=quiz_or_final, **payload)


def _create_quiz_questions_bulk(quiz, questions_data):
    """Create many quiz questions with a single bulk insert."""
    question_rows = []
    for q_idx, q in enumerate(questions_data):
        payload = _parse_quiz_question_payload(q, q_idx)
        if payload:
            question_rows.append(QuizQuestion(quiz=quiz, **payload))

    _bulk_create_with_db_retry(QuizQuestion, question_rows, batch_size=BULK_CREATE_BATCH_SIZE)
    return len(question_rows)


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


def import_course_from_zip(zip_file_path, category=None, instructor=None, temp_dir=None):
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
                        FinalQuiz.objects.create(
                            course=course,
                            title=fq_data.get('title', 'Examen Final'),
                            num_questions=fq_data.get('num_questions', len(fq_questions)),
                            pass_threshold=fq_data.get('pass_threshold', 70),
                        )
                        logger.info(f"Created FinalQuiz with {len(fq_questions)} questions")
                    continue

                # ── Create Section for content levels ────────────────────
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
                # Track global slide index across all modules in this section
                # for flat slide_NN naming fallback resolution
                global_slide_idx = 0
                for mod_idx, m_data in enumerate(modules_data):
                    mod_title = m_data.get('title', f"Module {mod_idx+1}")
                    module_obj = Module.objects.create(
                        section=section,
                        title=mod_title,
                        sequence=mod_idx + 1
                    )

                    slides = m_data.get('slides', [])
                    lessons_to_create = []
                    pending_lesson_files = []

                    for slide_idx, slide_data in enumerate(slides):
                        global_slide_idx += 1
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

                        lessons_to_create.append(Lesson(
                            module=module_obj,
                            title=lesson_title[:300],
                            type=LessonType.SLIDE,
                            sequence=slide_idx + 1,
                            duration_seconds=duration_seconds,
                            slide_type=slide_type_val,
                            display_mode=display_mode_val,
                            content=slide_data,
                        ))

                        audio_filename = slide_data.get('audio')
                        slide_bg = slide_data.get('bg')
                        slide_bg_fallback = slide_data.get('bg_fallback')
                        audio_path_final = None
                        bg_path_final = None

                        # ── Resolve audio file path ──
                        if audio_filename:
                            ap = os.path.join(base_dir, 'audio', audio_filename)
                            if os.path.exists(ap):
                                audio_path_final = ap
                            else:
                                # Try alternative extensions
                                audio_stem = os.path.splitext(audio_filename)[0]
                                for ext in AUDIO_EXTENSIONS:
                                    alt = os.path.join(base_dir, 'audio', f"{audio_stem}.{ext}")
                                    if os.path.exists(alt):
                                        audio_path_final = alt
                                        audio_filename = f"{audio_stem}.{ext}"
                                        break

                        # ── Resolve slide bg file path ──
                        if slide_bg:
                            bp = os.path.join(base_dir, 'slides', slide_bg)
                            if not os.path.exists(bp):
                                level_dir = slide_bg.split('/')[0] if '/' in slide_bg else ''

                                # Strategy 1: Try primary path with alternative extensions
                                bg_stem = os.path.splitext(os.path.basename(slide_bg))[0]
                                for ext in SLIDE_EXTENSIONS:
                                    alt_path = os.path.join(base_dir, 'slides', level_dir, f"{bg_stem}.{ext}")
                                    if os.path.exists(alt_path):
                                        bp = alt_path
                                        slide_bg = f"{level_dir}/{bg_stem}.{ext}" if level_dir else f"{bg_stem}.{ext}"
                                        break

                                # Strategy 2: Flat slide_NN naming with multiple extensions
                                if not os.path.exists(bp):
                                    for ext in SLIDE_EXTENSIONS:
                                        fallback_name = f"slide_{str(global_slide_idx).zfill(2)}.{ext}"
                                        fallback_path = os.path.join(base_dir, 'slides', level_dir, fallback_name)
                                        if os.path.exists(fallback_path):
                                            bp = fallback_path
                                            slide_bg = f"{level_dir}/{fallback_name}" if level_dir else fallback_name
                                            break

                                # Strategy 3: Try bg_fallback path from normalize (chapter-based naming)
                                if not os.path.exists(bp) and slide_bg_fallback:
                                    fbp = os.path.join(base_dir, 'slides', slide_bg_fallback)
                                    if os.path.exists(fbp):
                                        bp = fbp
                                        slide_bg = slide_bg_fallback
                                    else:
                                        fb_stem = os.path.splitext(os.path.basename(slide_bg_fallback))[0]
                                        fb_level = slide_bg_fallback.split('/')[0] if '/' in slide_bg_fallback else level_dir
                                        for ext in SLIDE_EXTENSIONS:
                                            alt = os.path.join(base_dir, 'slides', fb_level, f"{fb_stem}.{ext}")
                                            if os.path.exists(alt):
                                                bp = alt
                                                slide_bg = f"{fb_level}/{fb_stem}.{ext}" if fb_level else f"{fb_stem}.{ext}"
                                                break

                            if os.path.exists(bp):
                                bg_path_final = bp

                        pending_lesson_files.append({
                            'audio_path': audio_path_final,
                            'audio_name': os.path.basename(audio_filename) if audio_filename else None,
                            'bg_path': bg_path_final,
                            'bg_name': os.path.basename(slide_bg) if slide_bg else None,
                        })

                    _bulk_create_with_db_retry(
                        Lesson,
                        lessons_to_create,
                        batch_size=BULK_CREATE_BATCH_SIZE,
                    )

                    # Some DB backends may not return PKs for bulk_create rows.
                    if any(lesson.id is None for lesson in lessons_to_create):
                        by_sequence = Lesson.objects.filter(
                            module=module_obj,
                            sequence__in=[lesson.sequence for lesson in lessons_to_create],
                        ).only('id', 'sequence').in_bulk(field_name='sequence')
                        for lesson in lessons_to_create:
                            existing = by_sequence.get(lesson.sequence)
                            if existing:
                                lesson.id = existing.id

                    for lesson, pending in zip(lessons_to_create, pending_lesson_files):
                        if not lesson.id:
                            logger.warning(
                                f"Skipping file mapping for lesson '{lesson.title}' in module '{module_obj.id}' because PK was not resolved"
                            )
                            continue
                        if pending['audio_path'] or pending['bg_path']:
                            lesson_file_mappings.append({
                                'lesson_id': lesson.id,
                                'audio_path': pending['audio_path'],
                                'audio_name': pending['audio_name'],
                                'bg_path': pending['bg_path'],
                                'bg_name': pending['bg_name'],
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
                    created_questions = _create_quiz_questions_bulk(quiz, questions_data)
                    logger.info(
                        f"Attached quiz '{quiz_title}' ({created_questions} questions) to section '{level_name}'"
                    )
                    
        if lesson_file_mappings:
            _start_upload_thread(temp_dir, should_cleanup, lesson_file_mappings)
        elif should_cleanup and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)

        return course
        
    except Exception:
        if should_cleanup and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def _start_upload_thread(temp_dir, should_cleanup, lesson_file_mappings):
    thread = threading.Thread(
        target=_upload_files_background,
        args=(temp_dir, should_cleanup, lesson_file_mappings),
        name='zip-import-upload-worker',
    )
    thread.daemon = False
    thread.start()
