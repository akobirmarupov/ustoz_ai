"""Tayyor .pptx va .docx fayllarni yasash."""
from datetime import datetime
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches
from pptx.util import Pt as PPt

NAVY = RGBColor(0x0F, 0x1F, 0x4B)
CYAN = RGBColor(0x00, 0xC2, 0xFF)
GOLD = RGBColor(0xF2, 0xB6, 0x32)
INK = RGBColor(0x26, 0x2F, 0x40)
MUTED = RGBColor(0x8A, 0x93, 0xA6)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

LABELS = {
    "uz": {"intro": "KIRISH", "conclusion": "XULOSA", "refs": "FOYDALANILGAN ADABIYOTLAR", "toc": "MUNDARIJA",
           "topic": "Mavzu", "by": "Bajardi", "checked": "Tekshirdi", "annotation": "Annotatsiya",
           "keywords": "Kalit so'zlar", "thanks": "E'tiboringiz uchun rahmat!",
           "referat": "REFERAT", "mustaqil": "MUSTAQIL ISH", "kurs": "KURS ISHI"},
    "ru": {"intro": "ВВЕДЕНИЕ", "conclusion": "ЗАКЛЮЧЕНИЕ", "refs": "СПИСОК ЛИТЕРАТУРЫ", "toc": "СОДЕРЖАНИЕ",
           "topic": "Тема", "by": "Выполнил(а)", "checked": "Проверил(а)", "annotation": "Аннотация",
           "keywords": "Ключевые слова", "thanks": "Спасибо за внимание!",
           "referat": "РЕФЕРАТ", "mustaqil": "САМОСТОЯТЕЛЬНАЯ РАБОТА", "kurs": "КУРСОВАЯ РАБОТА"},
    "en": {"intro": "INTRODUCTION", "conclusion": "CONCLUSION", "refs": "REFERENCES", "toc": "CONTENTS",
           "topic": "Topic", "by": "Prepared by", "checked": "Checked by", "annotation": "Abstract",
           "keywords": "Keywords", "thanks": "Thank you for your attention!",
           "referat": "ESSAY", "mustaqil": "INDEPENDENT WORK", "kurs": "COURSE PAPER"},
}


# ---------------- PowerPoint ----------------

def _rect(slide, x, y, w, h, color):
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    shape.line.fill.background()
    return shape


def _text(slide, x, y, w, h, text, size, color, bold=False, anchor=MSO_ANCHOR.TOP, align=PP_ALIGN.LEFT):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    for i, line in enumerate(text.split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        run = p.add_run()
        run.text = line
        run.font.size = PPt(size)
        run.font.bold = bold
        run.font.color.rgb = color
    return box


def build_pptx(data: dict, titul: list[str], lang: str, path: Path) -> Path:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    blank = prs.slide_layouts[6]

    s = prs.slides.add_slide(blank)
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = NAVY
    _rect(s, 0.8, 4.05, 1.6, 0.07, CYAN)
    _rect(s, 2.5, 3.98, 0.2, 0.2, GOLD)
    _text(s, 0.8, 1.2, 11.7, 2.7, data["title"], 40, WHITE, bold=True, anchor=MSO_ANCHOR.BOTTOM)
    if titul:
        _text(s, 0.8, 4.4, 11.7, 2.4, "\n".join(titul), 18, RGBColor(0xC9, 0xD6, 0xF0))

    total = len(data["slides"])
    for i, sl in enumerate(data["slides"], 1):
        s = prs.slides.add_slide(blank)
        _rect(s, 0, 0, 13.333, 0.14, NAVY)
        _text(s, 0.8, 0.45, 11.7, 1.0, sl["title"], 30, NAVY, bold=True, anchor=MSO_ANCHOR.BOTTOM)
        _rect(s, 0.8, 1.55, 1.1, 0.06, CYAN)
        bullets = sl["bullets"][:7]
        size = 20 if len(bullets) <= 5 else 18
        box = s.shapes.add_textbox(Inches(0.8), Inches(1.9), Inches(11.7), Inches(4.9))
        tf = box.text_frame
        tf.word_wrap = True
        for j, b in enumerate(bullets):
            p = tf.paragraphs[0] if j == 0 else tf.add_paragraph()
            p.space_after = PPt(10)
            dot = p.add_run()
            dot.text = "■  "
            dot.font.size = PPt(size - 6)
            dot.font.color.rgb = CYAN
            run = p.add_run()
            run.text = b
            run.font.size = PPt(size)
            run.font.color.rgb = INK
        _text(s, 11.6, 6.85, 1.2, 0.4, f"{i}/{total}", 12, MUTED, align=PP_ALIGN.RIGHT)
        _rect(s, 12.95, 6.95, 0.12, 0.12, GOLD)

    s = prs.slides.add_slide(blank)
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = NAVY
    _text(s, 0.8, 2.6, 11.7, 1.6, LABELS[lang]["thanks"], 40, WHITE, bold=True,
          anchor=MSO_ANCHOR.MIDDLE, align=PP_ALIGN.CENTER)
    _rect(s, 5.87, 4.3, 1.6, 0.07, CYAN)

    prs.save(path)
    return path


# ---------------- Word ----------------

def _setup(doc: Document):
    sec = doc.sections[0]
    sec.page_height, sec.page_width = Cm(29.7), Cm(21)
    sec.left_margin, sec.right_margin = Cm(3), Cm(1.5)
    sec.top_margin, sec.bottom_margin = Cm(2), Cm(2)
    st = doc.styles["Normal"]
    st.font.name = "Times New Roman"
    st.font.size = Pt(14)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
    st.paragraph_format.line_spacing = 1.5
    st.paragraph_format.space_after = Pt(0)
    _page_numbers(sec)


def _page_numbers(section):
    p = section.footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    for tag, text in (("begin", None), (None, "PAGE"), ("end", None)):
        if tag:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), tag)
        else:
            el = OxmlElement("w:instrText")
            el.set(qn("xml:space"), "preserve")
            el.text = text
        run._r.append(el)


def _p(doc, text="", *, bold=False, italic=False, size=None, align=WD_ALIGN_PARAGRAPH.JUSTIFY,
       indent=True, before=0, after=0):
    p = doc.add_paragraph()
    p.alignment = align
    pf = p.paragraph_format
    pf.first_line_indent = Cm(1.25) if indent else None
    pf.space_before, pf.space_after = Pt(before), Pt(after)
    if text:
        r = p.add_run(text)
        r.bold, r.italic = bold, italic
        if size:
            r.font.size = Pt(size)
    return p


def _heading(doc, text, size=14):
    _p(doc, text, bold=True, size=size, align=WD_ALIGN_PARAGRAPH.CENTER, indent=False, before=12, after=6)


def _page_break(doc):
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


def _title_page(doc, kind, data, titul, L):
    univ = titul[0] if titul else ""
    student = titul[1] if len(titul) > 1 else ""
    teacher = titul[2] if len(titul) > 2 else ""
    C = WD_ALIGN_PARAGRAPH.CENTER
    if univ:
        _p(doc, univ.upper(), bold=True, align=C, indent=False)
    for _ in range(7):
        _p(doc, indent=False)
    _p(doc, L[kind], bold=True, size=28, align=C, indent=False)
    _p(doc, f"{L['topic']}: {data['title']}", bold=True, size=16, align=C, indent=False, before=12)
    for _ in range(6):
        _p(doc, indent=False)
    R = WD_ALIGN_PARAGRAPH.RIGHT
    if student:
        _p(doc, f"{L['by']}: {student}", align=R, indent=False)
    if teacher:
        _p(doc, f"{L['checked']}: {teacher}", align=R, indent=False)
    for _ in range(4):
        _p(doc, indent=False)
    _p(doc, str(datetime.now().year), align=C, indent=False)
    _page_break(doc)


def _paragraphs(doc, items):
    for t in items:
        if t.strip():
            _p(doc, t.strip())


def build_docx(kind: str, data: dict, titul: list[str], lang: str, path: Path) -> Path:
    L = LABELS[lang]
    doc = Document()
    _setup(doc)

    if kind == "maqola":
        _p(doc, data["title"].upper(), bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, indent=False, after=6)
        if titul:
            _p(doc, ", ".join(titul), italic=True, align=WD_ALIGN_PARAGRAPH.CENTER, indent=False, after=12)
        if data.get("annotation"):
            p = _p(doc)
            p.add_run(f"{L['annotation']}: ").bold = True
            p.add_run(data["annotation"])
        if data.get("keywords"):
            p = _p(doc, after=12)
            p.add_run(f"{L['keywords']}: ").bold = True
            p.add_run(", ".join(data["keywords"]))
    else:
        _title_page(doc, kind, data, titul, L)
        _heading(doc, L["toc"])
        toc = [L["intro"]]
        for sec in data["sections"]:
            toc.append(sec["heading"])
            toc += [f"    {sub['heading']}" for sub in sec.get("subsections", [])]
        toc += [L["conclusion"], L["refs"]]
        for line in toc:
            _p(doc, line, indent=False)
        _page_break(doc)

    if data.get("introduction"):
        _heading(doc, L["intro"])
        _paragraphs(doc, data["introduction"])
    for sec in data["sections"]:
        _heading(doc, sec["heading"])
        _paragraphs(doc, sec.get("paragraphs", []))
        for sub in sec.get("subsections", []):
            _p(doc, sub["heading"], bold=True, indent=False, before=6, after=3)
            _paragraphs(doc, sub.get("paragraphs", []))
    if data.get("conclusion"):
        _heading(doc, L["conclusion"])
        _paragraphs(doc, data["conclusion"])
    if data.get("references"):
        _heading(doc, L["refs"])
        for i, ref in enumerate(data["references"], 1):
            _p(doc, f"{i}. {ref}", indent=False)

    doc.save(path)
    return path
