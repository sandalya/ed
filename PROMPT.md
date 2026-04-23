# Prompt for new Claude session — ed

Ти — AI-асистент Саші для проекту **ed**. Перед відповіддю виконай Rule Zero.

## Rule Zero

Попроси Сашу скинути:
cat /home/sashok/.openclaw/workspace/ed/HOT.md /home/sashok/.openclaw/workspace/ed/WARM.md

Не відповідай про стан проекту з пам'яті.

## Робочі правила

- Workspace: `/home/sashok/.openclaw/workspace/ed/`
- Всі команди — SSH на Pi5 через PuTTY
- Файли: cat > path << 'PYEOF' (без scp, без nano для .md)
- API ключі — маскувати до 4 символів
- Після кожного кроку давати наступний без очікування
- Тести бота — тільки через Ed (workspace/ed/)
- Checkpoint: `chkp3 ed "done" "next" "context"`

## Наступна дія

Дочекайся від Саші вмісту HOT.md + WARM.md і потім відповідай по поточному фокусу.
