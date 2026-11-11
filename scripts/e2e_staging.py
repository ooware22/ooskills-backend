"""
End-to-end test of staging (staging.ooskills.com + api-staging.ooskills.com).

It plays a real learner: public pages in three languages, sign-up and login
rules, then (with the verified test account) the free course from enrolment
to certificate, a paid checkout, the learner pages in a real browser and a
password change. It writes a PDF report with screenshots.

Setup (once):
    python -m venv .e2e && .e2e/Scripts/pip install playwright requests reportlab
    # The browser is the Microsoft Edge already installed on Windows.

Run:
    .e2e/Scripts/python scripts/e2e_staging.py --env-file ../.e2e-staging.env --out ../e2e-reports

The env file holds E2E_USER_EMAIL and E2E_USER_PASSWORD (the same password as
the STAGING_E2E_PASSWORD GitHub secret; the staging deploy creates the account
and resets it to a new learner). Without it, the learner part is skipped.

Side effects on staging only: one new unverified account per run
(e2e-signup-<time>@example.com, never e-mailed) and one pending Chargily
checkout that is never paid.
"""

import argparse
import json
import os
import secrets
import string
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

import requests

API = 'https://api-staging.ooskills.com/api'
WEB = 'https://staging.ooskills.com'
FREE = 'demo-gestion-de-projet-les-bases'
PAID = 'demo-communication-professionnelle'
ENGLISH = 'demo-personal-productivity-basics'
LOCALE_COOKIE = 'ooskills-locale'
UA = 'OoSkills-staging-e2e/1.0'

RESULTS = []        # {group, name, status, detail, shots}
CTX = {}            # shared state between steps
SHOTS_DIR = None


class Skip(Exception):
    pass


# ----------------------------------------------------------------- helpers

def step(group, name):
    def deco(fn):
        def run():
            entry = {'group': group, 'name': name, 'status': 'PASS', 'detail': '', 'shots': []}
            CTX['_shots'] = entry['shots']
            started = time.time()
            try:
                entry['detail'] = fn() or ''
            except Skip as e:
                entry['status'], entry['detail'] = 'SKIP', str(e)
            except AssertionError as e:
                entry['status'], entry['detail'] = 'FAIL', str(e) or 'check failed'
            except Exception as e:  # noqa: BLE001 - report everything
                entry['status'] = 'FAIL'
                entry['detail'] = f'{type(e).__name__}: {e}'
                traceback.print_exc()
            entry['seconds'] = round(time.time() - started, 1)
            RESULTS.append(entry)
            mark = {'PASS': 'ok  ', 'FAIL': 'FAIL', 'SKIP': 'skip'}[entry['status']]
            print(f'[{mark}] {group} | {name} | {entry["detail"]}', flush=True)
        run.__name__ = fn.__name__
        STEPS.append(run)
        return run
    return deco


STEPS = []


def http(method, url, token=None, retry=True, **kw):
    """requests with the test user agent; waits once on HTTP 429."""
    headers = kw.pop('headers', {}) or {}
    headers.setdefault('User-Agent', UA)
    if token:
        headers['Authorization'] = f'Bearer {token}'
    kw.setdefault('timeout', 40)
    res = requests.request(method, url, headers=headers, **kw)
    if res.status_code == 429 and retry:
        wait = min(int(res.headers.get('Retry-After', '60') or 60), 75) + 2
        print(f'      rate limited on {url}, waiting {wait}s', flush=True)
        time.sleep(wait)
        return http(method, url, token=token, retry=False, headers=headers, **kw)
    return res


def api(method, path, token=None, **kw):
    return http(method, API + path, token=token, **kw)


def rows(data):
    return data.get('results', data) if isinstance(data, dict) else data


def need_learner():
    if not CTX.get('token'):
        raise Skip(CTX.get('learner_skip', 'test account not logged in'))


def new_password():
    alphabet = string.ascii_letters + string.digits
    return 'Aa1-' + ''.join(secrets.choice(alphabet) for _ in range(20))


def shot(page, name, full_page=False):
    path = SHOTS_DIR / f'{len(list(SHOTS_DIR.glob("*.png"))) + 1:02d}_{name}.png'
    page.screenshot(path=str(path), full_page=full_page)
    CTX['_shots'].append(str(path))


# ----------------------------------------------------------------- 1. servers and catalogue
G1 = '1. Servers and catalogue'


@step(G1, 'API is up and is the staging one')
def t_health():
    d = api('GET', '/health/').json()
    assert d.get('status') == 'healthy', d
    assert d.get('environment') == 'staging', f'environment is {d.get("environment")}'
    return f'database {d.get("database")}, cache {d.get("cache")}'


@step(G1, 'Catalogue lists the 3 demo courses')
def t_catalogue():
    res = api('GET', '/formation/courses/')
    assert res.status_code == 200, res.status_code
    found = {c['slug']: c for c in rows(res.json())}
    missing = {FREE, PAID, ENGLISH} - set(found)
    assert not missing, f'missing: {", ".join(sorted(missing))}'
    CTX['courses'] = found
    return f'{len(found)} published course(s)'


@step(G1, 'Categories come from the API')
def t_categories():
    res = api('GET', '/formation/categories/')
    assert res.status_code == 200, res.status_code
    cats = rows(res.json())
    assert len(cats) >= 4, f'only {len(cats)} categories'
    return f'{len(cats)} categories'


@step(G1, 'Course page data and unknown course')
def t_course_detail():
    res = api('GET', f'/formation/courses/{FREE}/')
    assert res.status_code == 200, res.status_code
    d = res.json()
    assert d.get('is_free') is True, 'free course is not marked free'
    CTX['free_id'] = d['id']
    paid = api('GET', f'/formation/courses/{PAID}/').json()
    CTX['paid_id'] = paid['id']
    missing = api('GET', '/formation/courses/this-course-does-not-exist/')
    assert missing.status_code == 404, f'unknown course returns {missing.status_code}'
    return f'paid course price {paid.get("price")} DZD; unknown course returns 404'


# ----------------------------------------------------------------- 2. website pages
G2 = '2. Website pages'

PAGES = [
    ('/', 200), ('/courses', 200), (f'/courses/{FREE}', 200), ('/auth/signin', 200),
    ('/auth/signup', 200), ('/auth/forgot-password', 200), ('/privacy-policy', 200),
    ('/terms-of-service', 200), ('/verify/NOT-A-REAL-CODE', 200),
    ('/courses/this-course-does-not-exist', 404), ('/this-page-does-not-exist', 404),
]


@step(G2, 'Main pages answer with the right status')
def t_pages():
    bad = []
    for path, expected in PAGES:
        code = http('GET', WEB + path, allow_redirects=True).status_code
        if code != expected:
            bad.append(f'{path} → {code} (expected {expected})')
    assert not bad, '; '.join(bad)
    return f'{len(PAGES)} pages checked'


@step(G2, 'French, English and Arabic: language and direction from the server')
def t_languages():
    bad = []
    for loc in ('fr', 'en', 'ar'):
        html = http('GET', WEB + '/', cookies={LOCALE_COOKIE: loc}).text[:3000]
        if f'lang="{loc}"' not in html:
            bad.append(f'{loc}: lang attribute missing')
        if loc == 'ar' and 'dir="rtl"' not in html:
            bad.append('ar: dir="rtl" missing')
    assert not bad, '; '.join(bad)
    return 'lang="fr|en|ar", Arabic is right-to-left'


@step(G2, 'Security headers and no indexing of staging')
def t_headers():
    res = http('GET', WEB + '/')
    h = {k.lower(): v for k, v in res.headers.items()}
    problems = []
    if 'content-security-policy' not in h:
        problems.append('no Content-Security-Policy')
    if h.get('x-content-type-options', '').lower() != 'nosniff':
        problems.append('no X-Content-Type-Options: nosniff')
    noindex = 'noindex' in h.get('x-robots-tag', '').lower() or 'noindex' in res.text[:20000].lower()
    if not noindex:
        problems.append('staging can be indexed by Google (no noindex)')
    sec = http('GET', WEB + '/.well-known/security.txt')
    if sec.status_code != 200 or 'Contact:' not in sec.text:
        problems.append(f'security.txt {sec.status_code}')
    assert not problems, '; '.join(problems)
    return 'CSP, nosniff, noindex and security.txt present'


# ----------------------------------------------------------------- 3. sign-up and login rules
G3 = '3. Sign-up and login rules'


@step(G3, 'Sign-up gives no session before the e-mail is verified')
def t_signup():
    email = f'e2e-signup-{datetime.now():%Y%m%d%H%M%S}@example.com'
    pw = new_password()
    body = {'email': email, 'password': pw, 'password_confirm': pw, 'first_name': 'Essai',
            'last_name': 'Inscription', 'language': 'fr', 'accept_terms': True, 'age_confirmed': True}
    res = api('POST', '/auth/register/', json=body)
    assert res.status_code == 201, f'{res.status_code} {res.text[:200]}'
    d = res.json()
    assert 'access' not in d and 'tokens' not in d, 'tokens returned at sign-up'
    assert 'refresh' not in res.cookies, 'refresh cookie set at sign-up'
    CTX['signup'] = (email, pw, d)
    return f'201 "{d.get("message", "")[:80]}"'


@step(G3, 'Same answer for an address that already exists (no account enumeration)')
def t_signup_again():
    if 'signup' not in CTX:
        raise Skip('sign-up step failed')
    email, pw, first = CTX['signup']
    body = {'email': email, 'password': pw, 'password_confirm': pw, 'first_name': 'Essai',
            'last_name': 'Inscription', 'language': 'fr', 'accept_terms': True, 'age_confirmed': True}
    res = api('POST', '/auth/register/', json=body)
    assert res.status_code == 201, f'{res.status_code} {res.text[:200]}'
    assert res.json().get('message') == first.get('message'), 'different message for an existing address'
    return 'identical 201 response'


@step(G3, 'Sign-up refused without accepting the terms and the age check')
def t_signup_terms():
    pw = new_password()
    body = {'email': f'e2e-noterms-{int(time.time())}@example.com', 'password': pw,
            'password_confirm': pw, 'first_name': 'Essai', 'last_name': 'Conditions', 'language': 'fr'}
    res = api('POST', '/auth/register/', json=body)
    assert res.status_code == 400, f'{res.status_code}'
    fields = set(res.json()) if isinstance(res.json(), dict) else set()
    assert {'accept_terms', 'age_confirmed'} & fields, f'errors on {sorted(fields)}'
    return f'400 on {", ".join(sorted({"accept_terms", "age_confirmed"} & fields))}'


@step(G3, 'Unverified account: told to verify only after the right password')
def t_login_unverified():
    if 'signup' not in CTX:
        raise Skip('sign-up step failed')
    email, pw, _ = CTX['signup']
    res = api('POST', '/auth/login/', json={'email': email, 'password': pw})
    assert res.status_code in (400, 401, 403), f'{res.status_code}'
    assert 'email_not_verified' in res.text, f'no email_not_verified code: {res.text[:200]}'
    return f'{res.status_code} email_not_verified'


@step(G3, 'Wrong password and unknown e-mail get the same message')
def t_login_generic():
    if 'signup' not in CTX:
        raise Skip('sign-up step failed')
    email, _, _ = CTX['signup']
    wrong = api('POST', '/auth/login/', json={'email': email, 'password': 'Wrong-password-123'})
    unknown = api('POST', '/auth/login/', json={'email': f'nobody-{int(time.time())}@example.com',
                                                 'password': 'Wrong-password-123'})
    assert wrong.status_code == unknown.status_code, f'{wrong.status_code} vs {unknown.status_code}'
    assert wrong.json() == unknown.json(), 'different bodies'
    return f'both {wrong.status_code}'


@step(G3, 'Resend-verification and forgot-password answer the same for any address')
def t_generic_mails():
    a = api('POST', '/auth/resend-verification/', json={'email': f'nobody-{int(time.time())}@example.com'})
    b = api('POST', '/auth/forgot-password/', json={'email': f'nobody-{int(time.time())}@example.com'})
    assert a.status_code == 200, f'resend {a.status_code}'
    assert b.status_code == 200, f'forgot {b.status_code}'
    return 'both 200'


# ----------------------------------------------------------------- 4. learner journey
G4 = '4. Learner journey (test account)'


@step(G4, 'Test account logs in')
def t_login():
    email, pw = CTX.get('e2e_email'), CTX.get('e2e_password')
    if not pw:
        CTX['learner_skip'] = 'no E2E_USER_PASSWORD given'
        raise Skip(CTX['learner_skip'])
    res = api('POST', '/auth/login/', json={'email': email, 'password': pw})
    if res.status_code != 200:
        CTX['learner_skip'] = (f'test account cannot log in ({res.status_code}): the '
                               'STAGING_E2E_PASSWORD secret is probably not set yet')
        raise Skip(CTX['learner_skip'])
    d = res.json()
    CTX['token'] = d.get('access') or (d.get('tokens') or {}).get('access')
    assert CTX['token'], 'no access token'
    assert 'refresh' in res.cookies or 'refresh_token' in str(res.headers.get('set-cookie', '')), \
        'no refresh cookie'
    return email


@step(G4, 'Profile')
def t_profile():
    need_learner()
    d = api('GET', '/auth/me/', token=CTX['token']).json()
    assert d.get('email') == CTX['e2e_email'], d
    assert d.get('has_password') is True, 'has_password missing'
    return f'{d.get("first_name")} {d.get("last_name")}'


def my_enrollment(slug):
    data = api('GET', '/formation/enrollments/', token=CTX['token']).json()
    return next((e for e in rows(data) if e.get('course_slug') == slug), None)


@step(G4, 'Enrol in the free course')
def t_enrol_free():
    need_learner()
    if my_enrollment(FREE):
        return 'already enrolled (account not reset since the last run)'
    res = api('POST', '/formation/orders/', token=CTX['token'],
              json={'course_ids': [CTX['free_id']], 'paymentMethod': 'edahabia',
                    'promo_code': '', 'use_wallet': False})
    assert res.status_code in (200, 201), f'{res.status_code} {res.text[:200]}'
    d = res.json()
    assert d.get('status') == 'paid', f'free order status {d.get("status")}'
    assert my_enrollment(FREE), 'no enrolment after the free order'
    return f'order {d.get("status")}, total {d.get("total")}'


@step(G4, 'Course content: slides and quizzes, answers hidden')
def t_content():
    need_learner()
    res = api('GET', f'/formation/sections/?course={FREE}', token=CTX['token'])
    assert res.status_code == 200, res.status_code
    sections = rows(res.json())
    lessons, quizzes = [], []
    for s in sections:
        for m in s.get('modules_list') or []:
            lessons += m.get('lessons_list') or []
        if s.get('quiz'):
            quizzes.append(s['quiz'])
    assert len(sections) == 2 and len(lessons) == 6, f'{len(sections)} sections, {len(lessons)} lessons'
    empty = [l['title'] for l in lessons
             if not ((l.get('content') or {}).get('visual_content') or {}).get('bullet_points')]
    assert not empty, f'lessons without slide content: {empty}'
    leaked = [q for quiz in quizzes for q in quiz.get('questions', []) if 'correct_answer' in q]
    assert not leaked, f'{len(leaked)} quiz answers sent to the learner'
    CTX['lessons'], CTX['quizzes'] = lessons, quizzes
    return f'{len(sections)} sections, {len(lessons)} slides, {len(quizzes)} quizzes; answers not exposed'


@step(G4, 'Final exam is locked before the lessons are done')
def t_exam_locked():
    need_learner()
    enr = my_enrollment(FREE)
    if enr and enr.get('status') == 'completed':
        raise Skip('course already completed in an earlier run')
    res = api('POST', '/formation/final-quiz/generate/', token=CTX['token'], json={'course_id': CTX['free_id']})
    assert res.status_code in (400, 403), f'{res.status_code}: exam opened too early'
    return f'{res.status_code} before completion'


@step(G4, 'Complete every lesson')
def t_lessons():
    need_learner()
    for l in CTX.get('lessons', []):
        res = api('POST', '/formation/progress/', token=CTX['token'],
                  json={'lesson_id': l['id'], 'completed': True, 'current_slide': 0,
                        'last_position': 0, 'time_spent_delta': 60})
        assert res.status_code in (200, 201), f'{l["title"]}: {res.status_code} {res.text[:150]}'
    enr = my_enrollment(FREE)
    assert float(enr.get('progress') or 0) >= 100, f'progress {enr.get("progress")}'
    assert enr.get('status') == 'completed', f'status {enr.get("status")}'
    return f'progress {enr.get("progress")}%, status {enr.get("status")}'


@step(G4, 'Section quizzes: a wrong try, then a pass')
def t_quizzes():
    need_learner()
    out = []
    for quiz in CTX.get('quizzes', []):
        qs = quiz.get('questions', [])
        first = api('POST', '/formation/quiz-attempts/', token=CTX['token'],
                    json={'quiz_id': quiz['id'], 'answers': {q['id']: 0 for q in qs}})
        assert first.status_code in (200, 201), f'{first.status_code} {first.text[:150]}'
        key = {f['question_id']: f['correct_answer'] for f in first.json().get('feedback', [])}
        assert len(key) == len(qs), 'feedback incomplete after the attempt'
        second = api('POST', '/formation/quiz-attempts/', token=CTX['token'],
                     json={'quiz_id': quiz['id'], 'answers': key})
        d = second.json()
        assert d.get('passed') is True, f'not passed with the right answers: {d.get("score")}'
        out.append(f'{first.json().get("score")}% then {d.get("score")}%')
    return '; '.join(out)


@step(G4, 'Final exam passed and certificate issued')
def t_exam():
    need_learner()
    known = {}
    for attempt in range(1, 5):
        gen = api('POST', '/formation/final-quiz/generate/', token=CTX['token'],
                  json={'course_id': CTX['free_id']})
        assert gen.status_code == 200, f'generate {gen.status_code} {gen.text[:150]}'
        qs = gen.json()['questions']
        answers = {q['id']: known.get(q['id'], 0) for q in qs}
        sub = api('POST', '/formation/final-quiz/submit/', token=CTX['token'],
                  json={'course_id': CTX['free_id'], 'question_ids': [q['id'] for q in qs], 'answers': answers})
        assert sub.status_code in (200, 201), f'submit {sub.status_code} {sub.text[:150]}'
        d = sub.json()
        for f in d.get('feedback', []):
            known[f['question_id']] = f['correct_answer']
        if d.get('passed'):
            cert = d.get('certificate') or {}
            CTX['cert_code'] = cert.get('code')
            return f'passed on attempt {attempt} with {d.get("score")}%; certificate {cert.get("code")}'
    raise AssertionError('final exam not passed after 4 attempts')


@step(G4, 'Certificate: listed, public check, PDF')
def t_certificate():
    need_learner()
    certs = rows(api('GET', '/formation/certificates/', token=CTX['token']).json())
    mine = next((c for c in certs if c.get('course') == CTX['free_id']), None)
    assert mine, 'certificate not in the learner list'
    code = CTX['cert_code'] = mine['code']
    pub = http('GET', f'{API}/formation/certificates/verify/{code}/')
    assert pub.status_code == 200, f'public check {pub.status_code}'
    pdf = api('GET', f'/formation/certificates/export/{code}/pdf/?lang=fr', token=CTX['token'])
    assert pdf.status_code == 200 and pdf.content[:4] == b'%PDF', f'PDF {pdf.status_code} {pdf.headers.get("content-type")}'
    return f'{code}: public check 200, PDF {len(pdf.content) // 1024} KB'


@step(G4, 'Paid course: Chargily checkout created, order stays unpaid')
def t_paid():
    need_learner()
    res = api('POST', '/formation/orders/', token=CTX['token'],
              json={'course_ids': [CTX['paid_id']], 'paymentMethod': 'edahabia',
                    'promo_code': '', 'use_wallet': False})
    assert res.status_code in (200, 201), f'{res.status_code} {res.text[:200]}'
    d = res.json()
    url = d.get('checkout_url') or ''
    assert 'chargily' in url, f'no Chargily checkout URL (status {d.get("status")}): check the Chargily keys on staging'
    assert d.get('status') == 'pending', f'status {d.get("status")}'
    confirm = api('POST', f'/formation/orders/{d["id"]}/confirm-payment/', token=CTX['token'])
    after = api('GET', f'/formation/orders/{d["id"]}/', token=CTX['token']).json()
    assert after.get('status') != 'paid', 'order became paid without payment'
    assert not my_enrollment(PAID), 'enrolled without paying'
    CTX['paid_order'] = d['id']
    return f'total {d.get("total")} DZD, checkout on {url.split("/")[2]}; confirm-payment {confirm.status_code}, still {after.get("status")}'


# ----------------------------------------------------------------- 5. browser
G5 = '5. In the browser (Microsoft Edge)'


def browser_steps():
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.launch(channel='msedge')
    CTX['browser'] = (pw, browser)
    return browser


@step(G5, 'Home and catalogue (desktop)')
def t_b_home():
    browser = CTX['browser'][1]
    ctx = browser.new_context(viewport={'width': 1366, 'height': 900}, locale='fr-FR', user_agent=UA)
    page = ctx.new_page()
    errors = []
    page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
    page.goto(WEB + '/', wait_until='networkidle')
    page.wait_for_timeout(1500)
    shot(page, 'home_desktop')
    home_text = page.inner_text('body')
    page.goto(WEB + '/courses', wait_until='networkidle')
    page.wait_for_timeout(1500)
    shot(page, 'catalogue_desktop')
    text = page.inner_text('body')
    missing = [t for t in ('Gestion de projet : les bases', 'Communication professionnelle',
                           'Personal productivity basics') if t not in text]
    page.goto(WEB + '/courses?category=communication', wait_until='networkidle')
    page.wait_for_timeout(1500)
    filtered = page.inner_text('body')
    shot(page, 'catalogue_filtered')
    ctx.close()
    assert not missing, f'catalogue does not show: {missing}'
    assert 'Communication professionnelle' in filtered and 'Personal productivity basics' not in filtered, \
        'category filter from the URL does not work'
    assert 'Gestion de projet' in home_text, 'home categories not shown'
    assert not errors, f'{len(errors)} console error(s) on home/catalogue: {errors[0][:150]}'
    return 'courses and categories shown, ?category= filter works, no console error'


@step(G5, 'Phone screens: no sideways scrolling')
def t_b_mobile():
    browser = CTX['browser'][1]
    bad = []
    for loc, paths in (('fr', ['/', '/courses', '/auth/signup', '/auth/signin', '/auth/forgot-password',
                               f'/courses/{FREE}']),
                       ('ar', ['/', '/auth/signup'])):
        ctx = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True,
                                  device_scale_factor=2, user_agent=UA)
        ctx.add_cookies([{'name': LOCALE_COOKIE, 'value': loc, 'url': WEB}])
        page = ctx.new_page()
        for path in paths:
            page.goto(WEB + path, wait_until='networkidle')
            page.wait_for_timeout(1200)
            over = page.evaluate('document.documentElement.scrollWidth - window.innerWidth')
            if over > 1:
                bad.append(f'{loc} {path} (+{over}px)')
            if path in ('/', '/auth/signup', '/courses') or over > 1:
                shot(page, f'mobile_{loc}_{path.strip("/").replace("/", "_") or "home"}')
        if loc == 'ar':
            assert page.evaluate('document.documentElement.dir') == 'rtl', 'Arabic page is not right-to-left'
        ctx.close()
    assert not bad, 'pages wider than the phone: ' + ', '.join(bad)
    return '8 pages at 390 px wide, Arabic right-to-left'


@step(G5, 'Learner pages after signing in through the form')
def t_b_learner():
    need_learner()
    browser = CTX['browser'][1]
    ctx = browser.new_context(viewport={'width': 1366, 'height': 900}, locale='fr-FR', user_agent=UA)
    page = ctx.new_page()
    page.goto(WEB + '/auth/signin', wait_until='networkidle')
    page.fill('#si-email', CTX['e2e_email'])
    page.fill('#si-password', CTX['e2e_password'])
    page.click('button[type=submit]')
    page.wait_for_url(lambda u: '/auth/signin' not in u, timeout=30000)
    problems = []
    for path, name, expect in (('/dashboard', 'dashboard', None),
                               ('/dashboard/my-courses', 'my_courses', 'Gestion de projet'),
                               ('/dashboard/orders', 'orders', 'Communication professionnelle'),
                               ('/dashboard/certificates', 'certificates', 'Gestion de projet'),
                               (f'/courses/{FREE}/learn', 'player', None)):
        page.goto(WEB + path, wait_until='networkidle')
        page.wait_for_timeout(2000)
        shot(page, name)
        body = page.inner_text('body')
        if '/auth/signin' in page.url:
            problems.append(f'{path} sent back to sign-in')
        elif expect and expect not in body:
            problems.append(f'{path} does not show "{expect}"')
        if path.endswith('/learn') and 'No visual content' in body:
            problems.append('player shows "No visual content"')
    if CTX.get('cert_code'):
        page.goto(f'{WEB}/verify/{CTX["cert_code"]}', wait_until='networkidle')
        page.wait_for_timeout(2500)
        shot(page, 'certificate_public')
        if 'Test' not in page.inner_text('body'):
            problems.append('public certificate page does not show the learner name')
    ctx.close()
    assert not problems, '; '.join(problems)
    return 'dashboard, my courses, orders, certificates, player and public certificate page'


@step(G4, 'Change the password, old one refused, then change it back')
def t_password():
    need_learner()
    original, temp = CTX['e2e_password'], new_password()
    res = api('PUT', '/auth/change-password/', token=CTX['token'],
              json={'old_password': original, 'new_password': temp, 'new_password_confirm': temp})
    assert res.status_code == 200, f'{res.status_code} {res.text[:200]}'
    new_token = (res.json().get('tokens') or {}).get('access')
    assert new_token, 'no new access token'
    old = api('POST', '/auth/login/', json={'email': CTX['e2e_email'], 'password': original})
    back = api('PUT', '/auth/change-password/', token=new_token,
               json={'old_password': temp, 'new_password': original, 'new_password_confirm': original})
    assert back.status_code == 200, f'could not restore the password ({back.status_code}); the next staging deploy resets it'
    assert old.status_code == 401, f'old password still accepted ({old.status_code})'
    CTX['token'] = (back.json().get('tokens') or {}).get('access') or new_token
    return 'changed, old password refused (401), restored'


@step(G4, 'Log out')
def t_logout():
    need_learner()
    res = api('POST', '/auth/logout/', token=CTX['token'])
    assert res.status_code in (200, 204, 205), res.status_code
    return f'{res.status_code}'


# ----------------------------------------------------------------- report

def write_pdf(path, started, finished):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape

    font = 'Helvetica'
    for f, n in (('C:/Windows/Fonts/arial.ttf', 'Arial'), ('C:/Windows/Fonts/arialbd.ttf', 'Arial-Bold')):
        if Path(f).exists():
            pdfmetrics.registerFont(TTFont(n, f))
            font = 'Arial'
    bold = 'Arial-Bold' if font == 'Arial' else 'Helvetica-Bold'
    base = ParagraphStyle('b', fontName=font, fontSize=8.5, leading=11)
    small = ParagraphStyle('s', parent=base, fontSize=7.5, leading=9.5, textColor=colors.HexColor('#52606d'))
    h1 = ParagraphStyle('h1', parent=base, fontName=bold, fontSize=18, leading=22)
    h2 = ParagraphStyle('h2', parent=base, fontName=bold, fontSize=12, leading=15, spaceBefore=8, spaceAfter=4)
    white = ParagraphStyle('w', parent=base, fontName=bold, textColor=colors.white)
    tone = {'PASS': ('#e3f9e5', '#1f7a33', 'Passed'), 'FAIL': ('#ffe3e3', '#a61b1b', 'Failed'),
            'SKIP': ('#eef0f2', '#3e4c59', 'Skipped')}

    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm, title='OoSkills staging test')
    W = doc.width
    n = {s: sum(1 for r in RESULTS if r['status'] == s) for s in tone}
    story = [Paragraph('OoSkills – automatic test of staging', h1), Spacer(1, 2 * mm),
             Paragraph(f'{WEB} and {API} · {started:%d %B %Y, %H:%M} → {finished:%H:%M}', small),
             Spacer(1, 4 * mm)]
    verdict = ('Everything passed.' if not n['FAIL'] and not n['SKIP'] else
               f'{n["FAIL"]} check(s) failed.' if n['FAIL'] else f'No failure, but {n["SKIP"]} check(s) skipped.')
    box = Table([[Paragraph(f'<b>{n["PASS"]} passed · {n["FAIL"]} failed · {n["SKIP"]} skipped</b><br/>{verdict}',
                            ParagraphStyle('v', parent=base, fontSize=10, leading=14))]], colWidths=[W])
    box.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), colors.HexColor(tone['FAIL' if n['FAIL'] else 'PASS'][0])),
                             ('LEFTPADDING', (0, 0), (-1, -1), 8), ('TOPPADDING', (0, 0), (-1, -1), 6),
                             ('BOTTOMPADDING', (0, 0), (-1, -1), 7)]))
    story += [box, Spacer(1, 3 * mm)]

    groups = []
    for r in RESULTS:
        if r['group'] not in groups:
            groups.append(r['group'])
    for g in groups:
        story.append(Paragraph(g, h2))
        data = [[Paragraph(h, white) for h in ('Check', 'Result', 'Details')]]
        style = [('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#243b53')),
                 ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#d9e2ec')), ('VALIGN', (0, 0), (-1, -1), 'TOP')]
        for i, r in enumerate([r for r in RESULTS if r['group'] == g], start=1):
            bg, fg, label = tone[r['status']]
            data.append([Paragraph(escape(r['name']), base),
                         Paragraph(f'<font color="{fg}"><b>{label}</b></font>', base),
                         Paragraph(escape(r['detail']), base)])
            style.append(('BACKGROUND', (1, i), (1, i), colors.HexColor(bg)))
        t = Table(data, colWidths=[62 * mm, 18 * mm, W - 80 * mm], repeatRows=1)
        t.setStyle(TableStyle(style))
        story.append(t)

    story += [Spacer(1, 4 * mm), Paragraph(
        'Side effects on staging only: one unverified account e2e-signup-…@example.com (never e-mailed) and one '
        'unpaid Chargily checkout per run. The test account is reset to a new learner by each staging deploy.', small)]

    shots = [(r['name'], s) for r in RESULTS for s in r['shots']]
    if shots:
        story += [PageBreak(), Paragraph('Screenshots', h2)]
        for name, s in shots:
            from PIL import Image as PILImage
            with PILImage.open(s) as im:
                w, h = im.size
            max_w, max_h = (W, 118 * mm) if w > h else (60 * mm, 125 * mm)
            scale = min(max_w / w, max_h / h)
            story.append(KeepTogether([Paragraph(f'{escape(Path(s).stem[3:].replace("_", " "))} — {escape(name)}', small),
                                       Spacer(1, 1 * mm), Image(s, width=w * scale, height=h * scale),
                                       Spacer(1, 4 * mm)]))
    doc.build(story)


def main():
    global SHOTS_DIR
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[1])
    ap.add_argument('--env-file', help='file with E2E_USER_EMAIL / E2E_USER_PASSWORD')
    ap.add_argument('--out', default='e2e-reports', help='folder for the report')
    ap.add_argument('--no-browser', action='store_true', help='skip the browser checks')
    args = ap.parse_args()

    if args.env_file and Path(args.env_file).exists():
        for line in Path(args.env_file).read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())
    CTX['e2e_email'] = os.environ.get('E2E_USER_EMAIL', 'e2e@ooskills.com')
    CTX['e2e_password'] = os.environ.get('E2E_USER_PASSWORD', '')

    started = datetime.now()
    out = Path(args.out) / f'{started:%Y-%m-%d_%H%M}'
    SHOTS_DIR = out / 'screenshots'
    SHOTS_DIR.mkdir(parents=True, exist_ok=True)

    browser_ok = False
    if not args.no_browser:
        try:
            browser_steps()
            browser_ok = True
        except Exception as e:  # noqa: BLE001
            CTX['browser_error'] = f'browser not available: {e}'
    for run in STEPS:
        if run.__name__.startswith('t_b_') and not browser_ok:
            RESULTS.append({'group': G5, 'name': run.__name__, 'status': 'SKIP',
                            'detail': CTX.get('browser_error', 'browser checks disabled'), 'shots': []})
            continue
        run()
    if browser_ok:
        pw, browser = CTX['browser']
        browser.close()
        pw.stop()

    finished = datetime.now()
    (out / 'results.json').write_text(json.dumps(RESULTS, indent=2, ensure_ascii=False), encoding='utf-8')
    pdf = out / f'OoSkills_test_staging_{started:%Y-%m-%d_%H%M}.pdf'
    write_pdf(pdf, started, finished)
    n = {s: sum(1 for r in RESULTS if r['status'] == s) for s in ('PASS', 'FAIL', 'SKIP')}
    print(f'\n{n["PASS"]} passed, {n["FAIL"]} failed, {n["SKIP"]} skipped\nReport: {pdf}')
    return 1 if n['FAIL'] else 0


if __name__ == '__main__':
    sys.exit(main())
