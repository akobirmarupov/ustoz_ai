"""AI'siz avtomatik o'qish: javoblari belgilangan tayyor testlarni savol + variant + to'g'ri javobga ajratadi.

Qo'llab-quvvatlanadigan formatlar:
1) Raqamlangan testlar, to'g'ri javob variant oldida yoki ortida belgi bilan:  *A) ...   +B) ...   #C) ...   D) ... *
2) Savol ichida javob qatori:  «Javob: B», «To'g'ri javob: B», «Answer: B», «Ответ: Б»
3) Fayl oxirida javoblar kaliti:  «Javoblar: 1-A 2-C 3-B ...» yoki har qatorda «1. A»
4) HEMIS formati:  savollar «++++» bilan, variantlar «====» bilan ajratilgan, to'g'ri javob oldida «#»
5) Teg formati:  <question> savol <variant> to'g'ri javob <variant> ... (birinchi variant — to'g'ri)
"""
import re

LATIN = "ABCDEF"
CYRILLIC = "АБВГДЕ"
MARKS = "*+#✓✔"

QUESTION_START = re.compile(r"(?m)^[ \t]*(\d{1,4})[ \t]*[.)][ \t]+(?=\S)")
OPTION = re.compile(r"^\s*([*+#✓✔]?)\s*([A-Fa-fА-Еа-е])\s*[).]\s*(.*?)\s*([*+✓✔]?)\s*$")
INLINE_OPTION = re.compile(r"(?:(?<=\s)|^)([*+#✓✔]?)([A-Fa-fА-Еа-е])\)\s*")
ANSWER_LINE = re.compile(r"(?i)^\s*(?:to['‘’`]?g['‘’`]?ri\s+)?(?:javob(?:i)?|answer|ответ|правильный ответ|kalit)\s*[:\-–]\s*"
                         r"([A-Fa-fА-Еа-е])\b")
KEY_HEADING = re.compile(r"(?im)^\s*(?:javoblar(?:\s+kaliti)?|javob\s+kaliti|kalitlar|answers?(?:\s+key)?|ответы|"
                         r"to['‘’`]?g['‘’`]?ri\s+javoblar)\s*[:\-–]?\s*")
KEY_PAIR = re.compile(r"(?<!\d)(\d{1,4})\s*[-.):]?\s*([A-Fa-fА-Еа-е])(?![\w'‘’])")


def letter_index(ch: str) -> int | None:
    up = ch.upper()
    if up in LATIN:
        return LATIN.index(up)
    if up in CYRILLIC:
        return CYRILLIC.index(up)
    return None


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _question(text: str, options: list[str], answer: int | None) -> dict | None:
    text = _clean(text)
    options = [_clean(o) for o in options if _clean(o)]
    if not text or len(options) < 2 or answer is None or not 0 <= answer < len(options):
        return None
    return {"question": text, "options": options[:6], "answer": answer, "confident": True}


# ---------------- 4) HEMIS: ++++ / ==== / # ----------------

def _parse_hemis(text: str) -> tuple[list[dict], int]:
    out, skipped = [], 0
    for block in re.split(r"\n\s*\+{4,}\s*\n?", text):
        parts = [p.strip() for p in re.split(r"\n?\s*={4,}\s*\n?", block) if p.strip()]
        if len(parts) < 3:
            if parts:
                skipped += 1
            continue
        options, answer = [], None
        for i, opt in enumerate(parts[1:]):
            if opt.startswith("#"):
                answer, opt = i, opt[1:]
            options.append(opt)
        q = _question(parts[0], options, answer)
        if q:
            out.append(q)
        else:
            skipped += 1
    return out, skipped


# ---------------- 5) <question> / <variant> ----------------

def _parse_tags(text: str) -> tuple[list[dict], int]:
    out, skipped = [], 0
    for block in re.split(r"(?i)<question\d*>", text)[1:]:
        parts = re.split(r"(?i)<variant(?:right)?>", block)
        q = _question(parts[0], parts[1:], 0)  # birinchi variant — to'g'ri javob
        if q:
            out.append(q)
        else:
            skipped += 1
    return out, skipped


# ---------------- 1-3) Raqamlangan testlar ----------------

def _answer_key(text: str) -> tuple[str, dict[int, int]]:
    """Javoblar kalitini topadi va uni matndan ajratadi: (savollar matni, {raqam: javob})."""
    heading = None
    for m in KEY_HEADING.finditer(text):
        heading = m
    if heading:
        key_text, body = text[heading.end():], text[:heading.start()]
    else:
        # Sarlavhasiz: oxiridagi faqat «1-A 2-B» juftliklaridan iborat qatorlar
        lines = text.rstrip().split("\n")
        k = len(lines)
        while k > 0:
            line = lines[k - 1].strip()
            if not line:
                k -= 1
                continue
            rest = KEY_PAIR.sub("", line).strip(" ,;|\t")
            if KEY_PAIR.search(line) and not rest:
                k -= 1
            else:
                break
        key_text, body = "\n".join(lines[k:]), "\n".join(lines[:k])
    key = {}
    for num, letter in KEY_PAIR.findall(key_text):
        idx = letter_index(letter)
        if idx is not None:
            key[int(num)] = idx
    return (body, key) if len(key) >= 3 else (text, {})


def _split_options(lines: list[str]) -> list[str]:
    """«A) 1  B) 2  C) 3» kabi bir qatordagi variantlarni alohida qatorlarga ajratadi."""
    out = []
    for line in lines:
        hits = list(INLINE_OPTION.finditer(line))
        if len(hits) >= 2:
            for i, m in enumerate(hits):
                end = hits[i + 1].start() if i + 1 < len(hits) else len(line)
                out.append(line[m.start():end].strip())
        else:
            out.append(line)
    return out


def _parse_block(block: str, number: int, key: dict[int, int]) -> dict | None:
    body = QUESTION_START.sub("", block, count=1)
    lines = _split_options([ln for ln in body.split("\n") if ln.strip()])
    question, options, answer, seen_option = [], [], None, False
    for line in lines:
        am = ANSWER_LINE.match(line)
        if am:
            answer = letter_index(am.group(1))
            continue
        om = OPTION.match(line)
        if om and (seen_option or question):
            seen_option = True
            lead, _letter, text, trail = om.groups()
            if lead or trail:
                answer = len(options)
            options.append(text)
        elif seen_option and options:
            options[-1] += " " + line.strip()  # variant davomi
        else:
            question.append(line)
    if answer is None:
        answer = key.get(number)
    return _question(" ".join(question), options, answer)


def _parse_numbered(text: str) -> tuple[list[dict], int]:
    body, key = _answer_key(text)
    starts, expected = [], None
    for m in QUESTION_START.finditer(body):
        n = int(m.group(1))
        if expected is None or n == expected:
            starts.append((m.start(), n))
            expected = n + 1
    out, skipped = [], 0
    for i, (pos, n) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(body)
        q = _parse_block(body[pos:end], n, key)
        if q:
            out.append(q)
        else:
            skipped += 1
    return out, skipped


def parse_tests(text: str) -> tuple[list[dict], int]:
    """(savollar, tashlab ketilganlar soni). Javobi aniqlanmagan savollar tashlab ketiladi."""
    text = text.replace("\r", "")
    if re.search(r"(?i)<question\d*>", text):
        return _parse_tags(text)
    if re.search(r"\n\s*={4,}", text) and re.search(r"\n\s*\+{4,}", text):
        return _parse_hemis(text)
    return _parse_numbered(text)


FORMAT_HELP = (
    "📄 <b>Avtomatik usul uchun fayl formati</b> (har bir savolda to'g'ri javob belgilangan bo'lishi shart):\n\n"
    "<b>1-usul</b> — to'g'ri variant oldida * belgisi:\n"
    "<code>1. 2 + 2 = ?\nA) 3\n*B) 4\nC) 5\nD) 6</code>\n\n"
    "<b>2-usul</b> — har savoldan keyin javob qatori:\n"
    "<code>1. 2 + 2 = ?\nA) 3  B) 4  C) 5  D) 6\nJavob: B</code>\n\n"
    "<b>3-usul</b> — fayl oxirida javoblar kaliti:\n"
    "<code>Javoblar: 1-B 2-A 3-D ...</code>\n\n"
    "<b>4-usul</b> — HEMIS formati (++++, ====, # to'g'ri javob)."
)
