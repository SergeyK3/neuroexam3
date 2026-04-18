"""User-facing bot texts and lightweight language detection."""

from __future__ import annotations

import re

SUPPORTED_LANGS = {"ru", "kk", "en"}

_KAZAKH_CHARS_RE = re.compile(r"[әіңғүұқөһі]", re.IGNORECASE)
_CYRILLIC_RE = re.compile(r"[А-Яа-яЁёӘәІіҢңҒғҮүҰұҚқӨөҺһ]")
_LATIN_RE = re.compile(r"[A-Za-z]")

_TEXTS: dict[str, dict[str, str]] = {
    "welcome_start": {
        "ru": (
            "Экзамен начинается заново. Пожалуйста, успокойтесь, сделайте несколько глубоких вдохов и "
            "выдохов, не торопитесь и внимательно читайте вопросы."
        ),
        "kk": (
            "Емтихан қайта басталады. Өтінемін, сабыр сақтап, бірнеше рет терең дем алып-шығарыңыз, "
            "асықпай жауап беріп, сұрақтарды мұқият оқыңыз."
        ),
        "en": (
            "The exam is starting over. Please stay calm, take a few deep breaths, do not rush, "
            "and read the questions carefully."
        ),
    },
    "choose_language": {
        "ru": "Пожалуйста, выберите язык экзамена: Русский (1), Қазақ (2) или English (3).",
        "kk": "Емтихан тілін таңдаңыз: Русский (1), Қазақ (2) немесе English (3).",
        "en": "Please choose the exam language: Русский (1), Қазақ (2), or English (3).",
    },
    "send_start": {
        "ru": "Чтобы начать, отправьте команду /start или /new.",
        "kk": "Бастау үшін /start немесе /new командасын жіберіңіз.",
        "en": "To begin, send /start or /new.",
    },
    "send_start_first": {
        "ru": "Сначала отправьте команду /start или /new.",
        "kk": "Алдымен /start немесе /new командасын жіберіңіз.",
        "en": "Please send /start or /new first.",
    },
    "text_not_voice": {
        "ru": "На этом шаге нужен текст, а не голосовое сообщение.",
        "kk": "Бұл қадамда дауыс емес, мәтін керек.",
        "en": "This step requires text, not a voice message.",
    },
    "need_choose_language": {
        "ru": "Нужно выбрать язык: Русский (1), Қазақ (2) или English (3) (можно написать словом или цифрой).",
        "kk": "Тілді таңдаңыз: Русский (1), Қазақ (2) немесе English (3) (сөзбен де, санмен де болады).",
        "en": "Please choose a language: Русский (1), Қазақ (2), or English (3) (word or number is fine).",
    },
    "choose_discipline_intro": {
        "ru": "Выберите дисциплину (ответьте номером или кодом из списка):",
        "kk": "Пәнді таңдаңыз (тізімдегі нөмірмен немесе кодпен жауап беріңіз):",
        "en": "Choose a discipline (reply with the number or code from the list):",
    },
    "discipline_prompt_number": {
        "ru": "Укажите номер дисциплины (1…{count}) или код (например «{example}»).",
        "kk": "Пәннің нөмірін (1…{count}) немесе кодын көрсетіңіз (мысалы, «{example}»).",
        "en": "Enter the discipline number (1…{count}) or the code (for example, “{example}”).",
    },
    "discipline_not_matched": {
        "ru": "Не удалось сопоставить ответ с дисциплиной. Отправьте номер из списка (1…{count}) или точный код дисциплины.",
        "kk": "Жауап пәнмен сәйкестендірілмеді. Тізімнен нөмірді (1…{count}) немесе пәннің нақты кодын жіберіңіз.",
        "en": "Could not match your reply to a discipline. Send a list number (1…{count}) or the exact discipline code.",
    },
    "registration_prompt": {
        "ru": (
            "Нужны **четыре сведения по порядку**:\n"
            "1) Название дисциплины или курса\n"
            "2) Вид контроля (рубежный контроль или экзамен)\n"
            "3) Номер группы\n"
            "4) ФИО полностью\n\n"
            "Можно отправить **одним сообщением** (несколько строк или через `;` / `|`), "
            "или **несколькими сообщениями подряд** — если случайно нажали Enter, просто допишите в следующих сообщениях."
        ),
        "kk": (
            "**Төрт мәліметті ретімен** жіберіңіз:\n"
            "1) Пән немесе курс атауы\n"
            "2) Бақылау түрі (рубежный контроль немесе экзамен)\n"
            "3) Топ нөмірі\n"
            "4) ТАӘ толық\n\n"
            "Бәрін **бір хабарламамен** (бірнеше жолмен немесе `;` / `|` арқылы) не "
            "**бірнеше хабарламамен қатарынан** жібере аласыз."
        ),
        "en": (
            "Please provide **four items in order**:\n"
            "1) Discipline or course name\n"
            "2) Assessment type (midterm control or exam)\n"
            "3) Group number\n"
            "4) Full name\n\n"
            "You may send them **in one message** (multiple lines or separated by `;` / `|`) "
            "or **across several messages** if that is more convenient."
        ),
    },
    "registration_text_only": {
        "ru": "Отправьте регистрационные данные текстом (см. список выше).",
        "kk": "Тіркеу мәліметтерін мәтінмен жіберіңіз (жоғарыдағы тізімді қараңыз).",
        "en": "Please send the registration details as text (see the list above).",
    },
    "send_nonempty_text": {
        "ru": "Отправьте непустой текст.",
        "kk": "Бос емес мәтін жіберіңіз.",
        "en": "Please send non-empty text.",
    },
    "registration_progress": {
        "ru": "Принято ({n}/4). Дальше пришлите: **{field}** (отдельным сообщением или вместе с остальным — как удобно). Осталось полей: {remaining}.",
        "kk": "Қабылданды ({n}/4). Келесіде мына деректі жіберіңіз: **{field}** (бөлек не қалғанымен бірге — өзіңізге ыңғайлы). Қалған өрістер: {remaining}.",
        "en": "Received ({n}/4). Next, please send: **{field}** (separately or together with the rest, whichever is convenient). Remaining fields: {remaining}.",
    },
    "registration_field_course": {
        "ru": "название дисциплины или курса",
        "kk": "пән немесе курс атауы",
        "en": "discipline or course name",
    },
    "registration_field_control": {
        "ru": "вид контроля (рубежный контроль или экзамен)",
        "kk": "бақылау түрі (рубежный контроль немесе экзамен)",
        "en": "assessment type (midterm control or exam)",
    },
    "registration_field_group": {
        "ru": "номер группы",
        "kk": "топ нөмірі",
        "en": "group number",
    },
    "registration_field_name": {
        "ru": "ФИО полностью",
        "kk": "ТАӘ толық",
        "en": "full name",
    },
    "answering_prompt": {
        "ru": (
            "Спасибо. Теперь предоставьте данные для экзамена (при необходимости — отдельным сообщением):\n"
            "• Номер экзаменационного билета\n"
            "• Ключ вопроса\n"
            "• Ответ на вопрос\n"
            "• Ключ следующего вопроса и ответ (если есть)\n"
        ),
        "kk": (
            "Рақмет. Енді емтихан деректерін жіберіңіз (қажет болса, бөлек хабарламамен):\n"
            "• Емтихан билеті нөмірі\n"
            "• Сұрақ кілті\n"
            "• Сұраққа жауап\n"
            "• Келесі сұрақтың кілті және жауабы (бар болса)\n"
        ),
        "en": (
            "Thank you. Now send the exam details (in a separate message if needed):\n"
            "• Exam ticket number\n"
            "• Question key\n"
            "• Answer to the question\n"
            "• Next question key and answer (if any)\n"
        ),
    },
    "send_text_or_voice": {
        "ru": "Отправьте текстовый ответ или голосовое сообщение.",
        "kk": "Мәтіндік жауапты немесе дауыстық хабарламаны жіберіңіз.",
        "en": "Send a text answer or a voice message.",
    },
    "finish_phrase_only": {
        "ru": "Голосовые ответы оцениваются автоматически после распознавания речи. Текстовый ответ оценивается по сообщению с содержанием, а не только по фразе о завершении.",
        "kk": "Дауыстық жауаптар сөйлеу танылғаннан кейін автоматты бағаланады. Мәтіндік жауап тек аяқтау тіркесімен емес, мазмұнды хабарламамен бағаланады.",
        "en": "Voice answers are graded automatically after speech recognition. A text answer is graded from a substantive message, not just a completion phrase.",
    },
    "hint_refusal": {
        "ru": "Извините, я не могу подсказывать правильные ответы, формулировки или ключевые элементы. Пожалуйста, ответьте самостоятельно.",
        "kk": "Кешіріңіз, мен дұрыс жауапты, дайын тұжырымды немесе негізгі элементтерді айта алмаймын. Өтінемін, өзіңіз жауап беріңіз.",
        "en": "Sorry, I cannot provide correct answers, ready-made wording, or key answer elements. Please answer on your own.",
    },
    "exam_finished_restart": {
        "ru": "Экзамен завершён. Чтобы начать снова, отправьте /start или /new.",
        "kk": "Емтихан аяқталды. Қайта бастау үшін /start немесе /new жіберіңіз.",
        "en": "The exam is finished. To start again, send /start or /new.",
    },
    "unknown_state_restart": {
        "ru": "Неизвестное состояние. Попробуйте /start или /new.",
        "kk": "Белгісіз күй. /start немесе /new жіберіп көріңіз.",
        "en": "Unknown state. Try /start or /new.",
    },
    "cant_get_text_again": {
        "ru": "Не удалось получить текст ответа. Пришлите его ещё раз.",
        "kk": "Жауап мәтінін алу мүмкін болмады. Қайта жіберіңіз.",
        "en": "Could not get the answer text. Please send it again.",
    },
    "cant_get_text_for_scoring": {
        "ru": "Не удалось получить текст ответа для оценки. Пришлите ответ ещё раз.",
        "kk": "Бағалау үшін жауап мәтінін алу мүмкін болмады. Жауапты қайта жіберіңіз.",
        "en": "Could not get the answer text for grading. Please send the answer again.",
    },
    "only_completion_phrase": {
        "ru": "Пока распозналась только служебная фраза о завершении ответа. Пришлите содержательный ответ.",
        "kk": "Әзірге тек жауаптың аяқталғанын білдіретін қызметтік тіркес танылды. Мазмұнды жауап жіберіңіз.",
        "en": "Only a completion phrase was recognized so far. Please send a substantive answer.",
    },
    "config_error": {
        "ru": "Ошибка настроек таблиц/эталонов: {details}",
        "kk": "Кестелер/эталондар баптауларында қате бар: {details}",
        "en": "Configuration error for sheets/reference answers: {details}",
    },
    "no_references": {
        "ru": "Нет эталонов: настройте Google Sheet и ключ, либо MVP_REFERENCES_JSON / MVP_REFERENCE_ANSWER в .env.",
        "kk": "Эталондар жоқ: Google Sheet пен кілтті немесе .env ішіндегі MVP_REFERENCES_JSON / MVP_REFERENCE_ANSWER параметрлерін баптаңыз.",
        "en": "No reference answers found: configure Google Sheet and key, or MVP_REFERENCES_JSON / MVP_REFERENCE_ANSWER in .env.",
    },
    "no_questions_match": {
        "ru": "Не удалось подобрать вопросы для оценки по текущему ответу.",
        "kk": "Ағымдағы жауап бойынша бағалау үшін сұрақтарды таңдау мүмкін болмады.",
        "en": "Could not match questions for grading based on the current answer.",
    },
    "scoring_unavailable_1": {
        "ru": "Оценка недоступна: в .env задайте OPENAI_API_KEY.",
        "kk": "Бағалау қолжетімсіз: .env ішінде OPENAI_API_KEY орнатыңыз.",
        "en": "Grading is unavailable: set OPENAI_API_KEY in .env.",
    },
    "scoring_unavailable_2": {
        "ru": "Без ключа нельзя ни оценку по покрытию смысловых элементов, ни семантическое сравнение по эмбеддингам.",
        "kk": "Кілтсіз мағыналық элементтер бойынша бағалау да, эмбеддингтер арқылы семантикалық салыстыру да жұмыс істемейді.",
        "en": "Without the key, neither rubric scoring nor embedding-based semantic comparison can run.",
    },
    "note_label": {
        "ru": "Примечание:",
        "kk": "Ескерту:",
        "en": "Note:",
    },
    "full_transcript_label": {
        "ru": "Полный транскрибированный ответ:",
        "kk": "Толық транскрипцияланған жауап:",
        "en": "Full transcribed answer:",
    },
    "question_label": {
        "ru": "Вопрос {n}",
        "kk": "{n}-сұрақ",
        "en": "Question {n}",
    },
    "coverage_score_label": {
        "ru": "покрытие смысловых элементов: {score}/100",
        "kk": "мағыналық элементтерді қамту: {score}/100",
        "en": "coverage of semantic elements: {score}/100",
    },
    "covered_label": {
        "ru": "покрыто",
        "kk": "қамтылған",
        "en": "covered",
    },
    "partial_label": {
        "ru": "частично",
        "kk": "ішінара",
        "en": "partial",
    },
    "missing_label": {
        "ru": "пропущено",
        "kk": "қалдырылған",
        "en": "missing",
    },
    "conclusion_label": {
        "ru": "вывод",
        "kk": "қорытынды",
        "en": "summary",
    },
    "question_error": {
        "ru": "{question}: ошибка оценки: {details}",
        "kk": "{question}: бағалау қатесі: {details}",
        "en": "{question}: grading error: {details}",
    },
    "similarity_label": {
        "ru": "сходство: {score}",
        "kk": "ұқсастық: {score}",
        "en": "similarity: {score}",
    },
    "average_label": {
        "ru": "Средняя оценка по вопросам:",
        "kk": "Сұрақтар бойынша орташа баға:",
        "en": "Average score across questions:",
    },
    "pending_progress_completion": {
        "ru": "Принял часть ответа: {answered} из {target}. Фраза «Ответ закончен» учтена только как возможная граница между частями, но оценка будет после получения всех ответов по билету.",
        "kk": "Жауаптың бір бөлігі қабылданды: {answered} / {target}. «Жауап аяқталды» тіркесі тек бөліктер арасындағы шекара ретінде ескерілді, бірақ бағалау билеттегі барлық жауаптар келгеннен кейін жасалады.",
        "en": "Part of the answer has been received: {answered} out of {target}. The phrase “Answer finished” was treated only as a possible boundary between parts; grading will start after all answers for the ticket are received.",
    },
    "pending_progress_wait": {
        "ru": "Принял часть ответа: {answered} из {target}. Жду продолжение по следующим вопросам.",
        "kk": "Жауаптың бір бөлігі қабылданды: {answered} / {target}. Келесі сұрақтар бойынша жалғасын күтемін.",
        "en": "Part of the answer has been received: {answered} out of {target}. Waiting for the rest of the answers.",
    },
    "transcription_too_short": {
        "ru": "Распознано слишком мало текста из аудиозаписи, поэтому бот не может надёжно определить ответы по вопросам. Пришлите аудио ещё раз или отправьте ответ текстом.",
        "kk": "Аудиожазбадан тым аз мәтін танылды, сондықтан бот жауаптарды сенімді түрде анықтай алмайды. Аудионы қайта жіберіңіз немесе жауапты мәтінмен жолдаңыз.",
        "en": "Too little text was recognized from the audio, so the bot cannot reliably determine the answers. Please resend the audio or send the answer as text.",
    },
    "no_voice_attachment": {
        "ru": "Нет голосового вложения.",
        "kk": "Дауыстық тіркеме жоқ.",
        "en": "No voice attachment found.",
    },
    "no_voice_file_id": {
        "ru": "Не удалось получить file_id голосового.",
        "kk": "Дауыстық хабарламаның file_id мәнін алу мүмкін болмады.",
        "en": "Could not get the voice message file_id.",
    },
    "voice_processing_error": {
        "ru": "Ошибка обработки голоса: {details}",
        "kk": "Дауысты өңдеу қатесі: {details}",
        "en": "Voice processing error: {details}",
    },
    "timeout_restart": {
        "ru": "Время экзамена истекло (2 часа с команды /start). Отправьте /start или /new, чтобы начать заново.",
        "kk": "Емтихан уақыты аяқталды (/start командасынан кейін 2 сағат). Қайта бастау үшін /start немесе /new жіберіңіз.",
        "en": "The exam time has expired (2 hours since /start). Send /start or /new to begin again.",
    },
    "preliminary_disclaimer": {
        "ru": "Это предварительная оценка.\nБот работает в тестовом режиме.\nОкончательную оценку выставляет преподаватель.",
        "kk": "Бұл алдын ала баға.\nБот тестілік режимде жұмыс істейді.\nҚорытынды бағаны оқытушы қояды.",
        "en": "This is a preliminary grade.\nThe bot is operating in test mode.\nThe final grade is assigned by the teacher.",
    },
}


def normalize_lang(lang: str | None) -> str:
    if isinstance(lang, str) and lang.strip().lower() in SUPPORTED_LANGS:
        return lang.strip().lower()
    return "ru"


def detect_message_language(text: str | None, fallback: str | None = "ru") -> str:
    raw = (text or "").strip()
    if not raw:
        return normalize_lang(fallback)
    # Command-only messages do not carry usable language cues.
    if raw.startswith("/") and len(raw.split()) == 1:
        return normalize_lang(fallback)
    if _KAZAKH_CHARS_RE.search(raw):
        return "kk"
    cyr = len(_CYRILLIC_RE.findall(raw))
    lat = len(_LATIN_RE.findall(raw))
    if lat > cyr and lat >= 2:
        return "en"
    if cyr:
        return "ru"
    return normalize_lang(fallback)


def t(key: str, lang: str | None = "ru", **kwargs: object) -> str:
    language = normalize_lang(lang)
    data = _TEXTS[key]
    template = data.get(language) or data["ru"]
    return template.format(**kwargs)
