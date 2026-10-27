"""AI bilan ishlash: hujjatlar, slaydlar, testlar va AI ustoz.

ANTHROPIC_API_KEY bo'lsa Claude ishlatiladi, bo'lmasa (vaqtincha) GEMINI_API_KEY orqali Gemini.
"""
import asyncio
import json
import logging
import os

import aiohttp
import anthropic

from data import config

log = logging.getLogger(__name__)

client = anthropic.AsyncAnthropic()  # ANTHROPIC_API_KEY .env dan olinadi

# Model xavfsizlik sababli rad etsa, server so'rovni mos zaxira modelga o'tkazadi
FALLBACK_BETAS = ["server-side-fallback-2026-07-01"]

LANG_NAMES = {"uz": "Uzbek (Latin script)", "ru": "Russian", "en": "English"}
WORDS_PER_PAGE = 280


class AIError(Exception):
    pass


async def _run(system: str, messages: list, *, max_tokens: int, effort: str, schema: dict | None = None):
    if not os.getenv("ANTHROPIC_API_KEY") and config.GEMINI_API_KEY:
        return await _run_gemini(system, messages, max_tokens=max_tokens, effort=effort, schema=schema)
    output_config = {"effort": effort}
    if schema:
        output_config["format"] = {"type": "json_schema", "schema": schema}
    try:
        async with client.beta.messages.stream(
            model=config.AI_MODEL,
            max_tokens=max_tokens,
            betas=FALLBACK_BETAS,
            fallbacks="default",
            system=system,
            messages=messages,
            output_config=output_config,
        ) as stream:
            msg = await stream.get_final_message()
    except TypeError as e:  # kalit umuman berilmagan
        log.error("Claude API kaliti topilmadi: %s", e)
        raise AIError("AI hali sozlanmagan (ANTHROPIC_API_KEY yo'q). Admin bilan bog'laning") from e
    except anthropic.AuthenticationError as e:
        log.error("Claude API kaliti noto'g'ri")
        raise AIError("AI kaliti noto'g'ri. Admin bilan bog'laning") from e
    except anthropic.RateLimitError as e:
        raise AIError("AI hozir band, birozdan keyin qayta urinib ko'ring") from e
    except anthropic.APIStatusError as e:
        log.error("Claude API xatosi %s: %s", e.status_code, e.message)
        raise AIError(f"AI xatosi ({e.status_code})") from e
    except anthropic.APIConnectionError as e:
        raise AIError("AI serveriga ulanib bo'lmadi") from e

    if msg.stop_reason == "refusal":
        raise AIError("AI bu so'rovni bajarmadi")
    if msg.stop_reason == "max_tokens":
        raise AIError("Javob juda uzun chiqdi")
    text = "".join(b.text for b in msg.content if b.type == "text")
    if schema:
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise AIError("AI javobini o'qib bo'lmadi") from e
    return text.strip()


GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"
GEMINI_THINKING = {"low": "low", "medium": "medium", "high": "high"}


async def _run_gemini(system: str, messages: list, *, max_tokens: int, effort: str, schema: dict | None):
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                     for m in messages],
        "generationConfig": {"maxOutputTokens": max_tokens,
                             "thinkingConfig": {"thinkingLevel": GEMINI_THINKING.get(effort, "low")}},
    }
    if schema:
        body["generationConfig"] |= {"responseMimeType": "application/json", "responseJsonSchema": schema}
    headers = {"x-goog-api-key": config.GEMINI_API_KEY}
    # Model band bo'lsa (503/429) bir oz kutib, zaxira model bilan qayta uriniladi
    models = [config.GEMINI_MODEL, config.GEMINI_FALLBACK_MODEL] * 2
    timeout = aiohttp.ClientTimeout(total=600)
    data = None
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for i, model in enumerate(models):
                async with session.post(GEMINI_URL.format(model), json=body, headers=headers) as resp:
                    data = await resp.json(content_type=None)
                    status = resp.status
                if status == 200:
                    break
                log.error("Gemini xatosi %s (%s): %s", status, model, (data.get("error") or {}).get("message"))
                if status in (400, 401, 403):
                    raise AIError("AI kaliti noto'g'ri. Admin bilan bog'laning")
                if status not in (429, 500, 503) or i == len(models) - 1:
                    raise AIError(f"AI xatosi ({status})" if status not in (429, 503)
                                  else "AI hozir band, birozdan keyin qayta urinib ko'ring")
                await asyncio.sleep(2 * (i + 1))
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        raise AIError("AI serveriga ulanib bo'lmadi") from e

    cand = (data.get("candidates") or [{}])[0]
    reason = cand.get("finishReason")
    if reason == "MAX_TOKENS":
        raise AIError("Javob juda uzun chiqdi")
    text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []) if not p.get("thought"))
    if not text:
        raise AIError("AI bu so'rovni bajarmadi")
    if schema:
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise AIError("AI javobini o'qib bo'lmadi") from e
    return text.strip()


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}

STR = {"type": "string"}
STR_LIST = {"type": "array", "items": STR}

OUTLINE_SCHEMA = _obj({"title": STR, "sections": STR_LIST})
SLIDES_SCHEMA = _obj({"title": STR, "slides": {"type": "array", "items": _obj({"title": STR, "bullets": STR_LIST})}})
_SUB = _obj({"heading": STR, "paragraphs": STR_LIST})
ESSE_SCHEMA = _obj({
    "title": STR, "subject": STR, "city": STR,
    "epigraph": STR, "epigraph_author": STR,
    "introduction": STR_LIST, "body": STR_LIST, "conclusion": STR_LIST, "references": STR_LIST,
})
DOC_SCHEMA = _obj({
    "title": STR,
    "annotation": STR,
    "keywords": STR_LIST,
    "introduction": STR_LIST,
    "sections": {"type": "array", "items": _obj({"heading": STR, "paragraphs": STR_LIST,
                                                  "subsections": {"type": "array", "items": _SUB}})},
    "conclusion": STR_LIST,
    "references": STR_LIST,
})
QUESTIONS_SCHEMA = _obj({"questions": {"type": "array", "items": _obj({
    "question": STR, "options": STR_LIST, "answer": {"type": "integer"}, "confident": {"type": "boolean"}})}})
RAW_QUESTIONS_SCHEMA = _obj({"questions": STR_LIST})

KIND_GUIDE = {
    "slide": "a presentation (slides)",
    "referat": "a university referat (short research essay)",
    "mustaqil": "a university independent work (mustaqil ish)",
    "esse": "a student essay (esse): a short, well-argued text with the author's own clear position, "
            "an introduction, 2-3 body sections developing the argument with examples, and a conclusion",
    "maqola": "a scientific article in IMRAD style (annotation, keywords, introduction, methods, results, "
              "discussion, conclusion)",
    "kurs": "a university course paper (kurs ishi) with an introduction, two chapters (I BOB, II BOB) of "
            "2-3 subsections each, and a conclusion",
}

WRITER_SYSTEM = (
    "You are an experienced academic writer for university students in Uzbekistan. "
    "You write original, well-structured, factually careful texts with no filler. "
    "Never invent precise statistics, quotes, or URLs; in references list real, well-known books, "
    "laws and official sources only."
)


async def make_outline(kind: str, topic: str, lang: str, size: int) -> dict:
    unit = "slides" if kind == "slide" else "pages"
    prompt = (f"Create the outline for {KIND_GUIDE[kind]} on the topic: «{topic}».\n"
              f"Language: {LANG_NAMES[lang]}. Target size: about {size} {unit}.\n"
              "Return a clear title and the list of main section headings (for slides: one heading per slide, "
              f"exactly {size - 2} items, excluding the title and closing slides).")
    return await _run(WRITER_SYSTEM, [{"role": "user", "content": prompt}],
                      max_tokens=4000, effort="low", schema=OUTLINE_SCHEMA)


async def make_slides(topic: str, lang: str, size: int, outline: dict) -> dict:
    prompt = (f"Write the content of a presentation on «{topic}» in {LANG_NAMES[lang]}.\n"
              f"Title: {outline['title']}\nSlide headings, in order:\n- " + "\n- ".join(outline["sections"]) +
              "\nFor every heading give 3-5 concise, informative bullet points (max ~20 words each). "
              "Return one slide per heading, in the same order.")
    return await _run(WRITER_SYSTEM, [{"role": "user", "content": prompt}],
                      max_tokens=16000, effort="medium", schema=SLIDES_SCHEMA)


async def make_document(kind: str, topic: str, lang: str, pages: int, outline: dict) -> dict:
    words = pages * WORDS_PER_PAGE
    prompt = (f"Write {KIND_GUIDE[kind]} on the topic «{topic}» in {LANG_NAMES[lang]}.\n"
              f"Title: {outline['title']}\nUse these main sections, in order:\n- " + "\n- ".join(outline["sections"]) +
              f"\nTotal length: about {words} words (≈{pages} pages, Times New Roman 14, 1.5 spacing). "
              "Paragraphs must be full academic paragraphs (4-7 sentences). "
              "Put the introduction and conclusion in their own fields, not in sections. "
              "Use subsections only where they fit (always for a course paper). "
              "annotation and keywords: fill them only for a scientific article, otherwise leave them empty. "
              + ("references: 0-3 real sources, only if they truly fit." if kind == "esse"
                 else "references: 6-12 real sources."))
    return await _run(WRITER_SYSTEM, [{"role": "user", "content": prompt}],
                      max_tokens=64000, effort="medium", schema=DOC_SCHEMA)


async def make_essay(topic: str, lang: str, pages: int, outline: dict, university: str = "") -> dict:
    words = pages * WORDS_PER_PAGE
    prompt = (f"Write a student essay (esse) on «{topic}» in {LANG_NAMES[lang]}.\n"
              f"Title: {outline['title']}\nCover these points in the main part, in order:\n- "
              + "\n- ".join(outline["sections"]) +
              f"\nTotal length: about {words} words (≈{pages} pages, Times New Roman 14, 1.5 spacing).\n"
              "introduction: 1 paragraph that ends with what the author will argue in this essay. "
              "body: 3-6 full paragraphs (4-7 sentences) developing the argument with facts and examples; "
              "include the author's own opinion in first person (e.g. «Mening fikrimcha...»). "
              "conclusion: 1 paragraph. "
              "subject: the university subject (fan) this topic belongs to, short, e.g. «O'zbekiston tarixi». "
              "epigraph / epigraph_author: a short real, well-known quote that fits the topic and its author "
              "(leave both empty if you are not sure the quote is real). "
              f"city: the city where this university is located: «{university or 'unknown'}» "
              "(if unknown, use Tashkent), written in the essay language. "
              "references: 3-6 real, well-known sources.")
    return await _run(WRITER_SYSTEM, [{"role": "user", "content": prompt}],
                      max_tokens=16000, effort="medium", schema=ESSE_SCHEMA)


TEST_SYSTEM = ("You are a meticulous subject-matter expert who prepares and checks multiple-choice tests. "
               "Accuracy of the correct answer matters more than anything else.")


async def answer_questions(raw_blocks: list[str]) -> list[dict]:
    """Javobsiz testlarni tozalaydi va to'g'ri javobni topadi."""
    text = "\n\n".join(raw_blocks)
    prompt = ("Below are multiple-choice test questions extracted from a document; the text may be messy.\n"
              "For each question, in the same order:\n"
              "- clean up the question text (no number prefix);\n"
              "- list its answer options WITHOUT letter or number prefixes;\n"
              "- answer: the 0-based index of the correct option;\n"
              "- confident: false if you are not sure, or the question is broken or ambiguous.\n"
              "If a question has no options, write 4 plausible options including the correct one.\n"
              "Keep the original language of each question. Do not skip or merge questions.\n\n" + text)
    data = await _run(TEST_SYSTEM, [{"role": "user", "content": prompt}],
                      max_tokens=32000, effort="high", schema=QUESTIONS_SCHEMA)
    return _clean_questions(data["questions"])


async def questions_from_text(source: str, count: int) -> list[dict]:
    """Kitobcha bo'lagidan test tuzadi."""
    prompt = (f"Create exactly {count} multiple-choice questions from the text below.\n"
              "- Write them in the same language as the text.\n"
              "- 4 options each, exactly one correct; vary the position of the correct option.\n"
              "- Every question must be answerable from the text; cover the whole excerpt, not only its start.\n"
              "- options without letter prefixes; answer is the 0-based index; confident=true.\n\nTEXT:\n" + source)
    data = await _run(TEST_SYSTEM, [{"role": "user", "content": prompt}],
                      max_tokens=32000, effort="medium", schema=QUESTIONS_SCHEMA)
    return _clean_questions(data["questions"])


async def split_raw_questions(text: str) -> list[str]:
    """Raqamlanmagan testlarni alohida savollarga ajratish (zaxira usul)."""
    prompt = ("Split the text below into individual test questions. Return each question together with its "
              "answer options as one raw text string, in the original order. Ignore headers, instructions and "
              "answer keys.\n\n" + text)
    data = await _run(TEST_SYSTEM, [{"role": "user", "content": prompt}],
                      max_tokens=32000, effort="low", schema=RAW_QUESTIONS_SCHEMA)
    return [q for q in data["questions"] if q.strip()]


def _clean_questions(items: list[dict]) -> list[dict]:
    out = []
    for q in items:
        opts = [o.strip() for o in q.get("options", []) if o and o.strip()][:6]
        if len(opts) < 2 or not q.get("question", "").strip():
            continue
        ans = q.get("answer", 0)
        if not isinstance(ans, int) or not 0 <= ans < len(opts):
            ans, q["confident"] = 0, False
        out.append({"question": q["question"].strip(), "options": opts, "answer": ans,
                    "confident": bool(q.get("confident", True))})
    return out


async def tutor_reply(subject: str, history: list[dict]) -> str:
    system = (f"You are «Ustoz Elite», a friendly tutor who prepares Uzbek school leavers (abituriyent) for "
              f"university entrance exams in {subject}. Answer in Uzbek (Latin script) unless the student writes "
              "in another language. Explain step by step, simply and briefly. Stay on educational topics; "
              "politely decline anything else. Output plain text for Telegram: no Markdown, no tables, "
              "no LaTeX — write formulas inline, e.g. x^2 + 3x = 0.")
    return await _run(system, history, max_tokens=3000, effort="low")
