from judge.rubrics.base import Rubric, RubricCriterion

SAM_RUBRIC = Rubric(
    name="Sam v1 — Personal Learning Agent",
    bot_description=(
        "Sam — особистий агент Олександра для навчання AI/агентній розробці. "
        "Персона Samwise. Спілкується українською. Має команди: /cur (curriculum), "
        "/done N (позначити тему виконаною), /hub (dashboard), /digest, /science, /profile. "
        "Curriculum складається з тем з полями title, estimate, why, read, do. "
        "Кожна тема рендериться з емодзі-заголовками: 💡 Навіщо, 🔗 Почитати, 🛠 Зробити руками."
    ),
    criteria=[
        RubricCriterion(
            name="no_raw_markdown",
            description=(
                "КРИТИЧНО. У відповіді бота немає сирих Markdown-символів що не відрендерились. "
                "Провал якщо в тексті зустрічаються одинарні *зірочки навколо слів* або "
                "_підкреслення навколо тексту_ які мали б бути форматуванням але показані сиро. "
                "Окей якщо * або _ зустрічаються всередині URL, коду, або як звичайний розділювач. "
                "Це захист від регресу Markdown-бага що був у shared/curriculum_engine.py."
            ),
            weight=2.5,
        ),
        RubricCriterion(
            name="no_traceback",
            description=(
                "У відповіді бота немає Python traceback, 'Error', 'Exception', "
                "'Traceback (most recent call last)', 'BadRequest', 'can't parse entities'. "
                "Бот має обробляти помилки gracefully."
            ),
            weight=2.5,
        ),
        RubricCriterion(
            name="responds_in_ukrainian",
            description=(
                "Основна мова відповіді — українська. Допускаються: назви технологій англійською "
                "(RAG, Tool Use, Agentic Loops), URL-посилання, коротка термінологія. "
                "Але загальний текст українською."
            ),
            weight=1.0,
        ),
        RubricCriterion(
            name="expected_content_present",
            description=(
                "Відповідь містить всі ключові елементи з expected_behavior.must_contain "
                "(якщо поле задане в тест-кейсі). Перевір кожен елемент по списку — "
                "якщо хоча б один відсутній, критерій провалено."
            ),
            weight=2.0,
        ),
        RubricCriterion(
            name="expected_buttons_present",
            description=(
                "Якщо тест-кейс очікує inline-кнопки (expected_behavior.must_have_buttons = true), "
                "у відповіді мають бути кнопки. Якщо заданий expected_behavior.button_count_min — "
                "кнопок має бути не менше. Це критично для curriculum та hub."
            ),
            weight=1.5,
        ),
        RubricCriterion(
            name="pinned_state_correct",
            description=(
                "Якщо у тест-кейсі задано expected_behavior.pinned_must_contain (список рядків) — "
                "ВСІ ці рядки мають бути у тексті закріпленого повідомлення (див. секцію "
                "'📌 Закріплене повідомлення' у мета-інформації). "
                "Якщо задано expected_behavior.pinned_must_be_empty=true — pinned має бути порожнім. "
                "Якщо pinned-related поля не задані в кейсі — критерій pass автоматично."
            ),
            weight=2.0,
        ),
        RubricCriterion(
            name="no_sycophantic_phrases",
            description=(
                "Без фраз 'Звісно!', 'Чудово!', 'Чудовий вибір!', 'Радий допомогти', "
                "'Звичайно!'. Sam — Samwise persona, надійний і спокійний, без підлабузництва."
            ),
            weight=1.0,
        ),
    ],
)
