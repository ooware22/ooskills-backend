"""
PDF Service — generates professional PDF certificates using ReportLab.

Creates an A4-landscape certificate with a decorative border, branding,
student info, and a verification code.
"""

import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm, mm
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


# ─── Color Palette (OOSkills gold/navy) ──────────────────────────────────────
GOLD = colors.HexColor('#D4A843')
NAVY = colors.HexColor('#1B2A4A')
DARK_GRAY = colors.HexColor('#333333')
LIGHT_GRAY = colors.HexColor('#888888')
CREAM = colors.HexColor('#FDF8F0')
BORDER_GOLD = colors.HexColor('#C49A30')


def generate_certificate_pdf(
    student_name: str,
    course_title: str,
    score: float,
    code: str,
    issued_at: datetime | None = None,
) -> bytes:
    """
    Generate a professional PDF certificate.

    Args:
        student_name: Full name of the student.
        course_title: Title of the completed course.
        score: Final quiz score (0-100).
        code: Unique verification code.
        issued_at: Date of issuance.

    Returns:
        PDF file content as bytes.
    """
    if issued_at is None:
        issued_at = datetime.now()

    buf = io.BytesIO()
    page_w, page_h = landscape(A4)
    c = canvas.Canvas(buf, pagesize=landscape(A4))

    # ── Background ──────────────────────────────────────────────────────────
    c.setFillColor(CREAM)
    c.rect(0, 0, page_w, page_h, fill=True, stroke=False)

    # ── Decorative Double Border ────────────────────────────────────────────
    margin = 1.5 * cm
    # Outer border
    c.setStrokeColor(BORDER_GOLD)
    c.setLineWidth(3)
    c.rect(margin, margin, page_w - 2 * margin, page_h - 2 * margin)
    # Inner border
    inner = margin + 6 * mm
    c.setLineWidth(1)
    c.rect(inner, inner, page_w - 2 * inner, page_h - 2 * inner)

    # ── Corner Ornaments ────────────────────────────────────────────────────
    ornament_size = 1.2 * cm
    c.setStrokeColor(GOLD)
    c.setLineWidth(2)
    corners = [
        (margin + 3 * mm, page_h - margin - 3 * mm),   # top-left
        (page_w - margin - 3 * mm, page_h - margin - 3 * mm),  # top-right
        (margin + 3 * mm, margin + 3 * mm),              # bottom-left
        (page_w - margin - 3 * mm, margin + 3 * mm),     # bottom-right
    ]
    for cx_pos, cy_pos in corners:
        c.circle(cx_pos, cy_pos, ornament_size / 3, fill=False)

    # ── Header: OOSkills Brand ──────────────────────────────────────────────
    y = page_h - 3.5 * cm
    c.setFillColor(NAVY)
    c.setFont('Helvetica-Bold', 14)
    c.drawCentredString(page_w / 2, y, 'OOSKILLS')

    # ── Gold Line ───────────────────────────────────────────────────────────
    y -= 0.8 * cm
    c.setStrokeColor(GOLD)
    c.setLineWidth(2)
    line_w = 6 * cm
    c.line(page_w / 2 - line_w / 2, y, page_w / 2 + line_w / 2, y)

    # ── Title: CERTIFICATE OF ACHIEVEMENT ───────────────────────────────────
    y -= 1.4 * cm
    c.setFillColor(NAVY)
    c.setFont('Helvetica-Bold', 28)
    c.drawCentredString(page_w / 2, y, 'CERTIFICATE OF ACHIEVEMENT')

    # ── Subtitle ────────────────────────────────────────────────────────────
    y -= 1 * cm
    c.setFillColor(LIGHT_GRAY)
    c.setFont('Helvetica', 11)
    c.drawCentredString(page_w / 2, y, 'This certificate is proudly presented to')

    # ── Student Name ────────────────────────────────────────────────────────
    y -= 1.5 * cm
    c.setFillColor(GOLD)
    c.setFont('Helvetica-Bold', 30)
    c.drawCentredString(page_w / 2, y, student_name)

    # ── Gold underline for name ─────────────────────────────────────────────
    y -= 0.4 * cm
    name_width = min(c.stringWidth(student_name, 'Helvetica-Bold', 30) + 2 * cm, page_w - 8 * cm)
    c.setStrokeColor(GOLD)
    c.setLineWidth(1)
    c.line(page_w / 2 - name_width / 2, y, page_w / 2 + name_width / 2, y)

    # ── Completion Text ─────────────────────────────────────────────────────
    y -= 1.0 * cm
    c.setFillColor(DARK_GRAY)
    c.setFont('Helvetica', 12)
    c.drawCentredString(
        page_w / 2, y,
        'for successfully completing the course',
    )

    # ── Course Title ────────────────────────────────────────────────────────
    y -= 1.2 * cm
    c.setFillColor(NAVY)
    # Auto-size font for long titles
    title_font_size = 22
    title_width = c.stringWidth(course_title, 'Helvetica-Bold', title_font_size)
    max_title_w = page_w - 8 * cm
    while title_width > max_title_w and title_font_size > 12:
        title_font_size -= 1
        title_width = c.stringWidth(course_title, 'Helvetica-Bold', title_font_size)
    c.setFont('Helvetica-Bold', title_font_size)
    c.drawCentredString(page_w / 2, y, course_title)

    # ── Footer Row: Date | Score | Code ─────────────────────────────────────
    y -= 2.0 * cm
    col_w = (page_w - 8 * cm) / 3
    x_start = 4 * cm

    footer_items = [
        ('DATE', issued_at.strftime('%B %d, %Y')),
        ('SCORE', f'{score:.0f}%'),
        ('VERIFICATION CODE', code),
    ]

    for i, (label, value) in enumerate(footer_items):
        x = x_start + col_w * i + col_w / 2

        c.setFillColor(LIGHT_GRAY)
        c.setFont('Helvetica', 8)
        c.drawCentredString(x, y + 0.4 * cm, label)

        c.setFillColor(NAVY)
        c.setFont('Helvetica-Bold', 12)
        c.drawCentredString(x, y - 0.2 * cm, value)

    # ── Separator lines between footer items ────────────────────────────────
    c.setStrokeColor(colors.HexColor('#D0D0D0'))
    c.setLineWidth(0.5)
    for i in range(1, 3):
        x = x_start + col_w * i
        c.line(x, y - 0.5 * cm, x, y + 0.8 * cm)

    # ── Bottom tag ──────────────────────────────────────────────────────────
    c.setFillColor(LIGHT_GRAY)
    c.setFont('Helvetica', 7)
    c.drawCentredString(
        page_w / 2, margin + 1 * cm,
        f'Verify at ooskills.com/verify/{code}',
    )

    c.save()
    buf.seek(0)
    return buf.read()
