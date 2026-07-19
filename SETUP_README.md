# Telegram-бот → Claude Code CLI: как это работает и как поднять у себя (macOS)

Это инструкция, как поднять **телеграм-бота, который управляет Claude Code через CLI**.
Ты пишешь боту в чат → бот запускает у себя на машине `claude` (Claude Code) в нужной папке
→ стримит ответ обратно в чат. Всё работает на твоём Mac, 24/7, как системный сервис.

> Здесь **только инфраструктурный слой** (чат ↔ CLI). Никакой чужой памяти, личности,
> баз данных или платёжных прокси тут нет — это ты дальше настраиваешь под себя.

---

## 1. Как это устроено (архитектура)

```
   ┌─────────────┐   long-poll    ┌──────────────────────┐   spawn proc   ┌──────────────┐
   │  Telegram   │ ─────────────▶ │  Python-бот          │ ─────────────▶ │  claude CLI  │
   │  (твой чат) │ ◀───────────── │  (claude-agent-sdk)  │ ◀───────────── │ (Claude Code)│
   └─────────────┘   edit message └──────────────────────┘   stream JSON  └──────────────┘
                                          │
                                   launchd держит процесс живым (KeepAlive)
```

Поток одного сообщения:

1. **Приём.** Бот на `python-telegram-bot` держит long-poll к Telegram. Пришло сообщение —
   проверяется, что отправитель в `ALLOWED_USERS` (белый список).
2. **Запуск Claude.** Бот вызывает `claude-agent-sdk` (Python-обёртка), которая **спавнит бинарь
   `claude`** (Claude Code CLI) по пути `CLAUDE_CLI_PATH`. Запуск идёт **в рабочей папке**
   (`cwd = APPROVED_DIRECTORY` или подпапка-проект).
3. **Контекст.** SDK передаёт CLI: твой промпт, модель (`CLAUDE_MODEL`), лимиты
   (`max_turns`, бюджет $), режим прав (`permission_mode`), и подмешивает `CLAUDE.md` из рабочей папки
   в system-prompt. Если есть прошлая сессия для этой пары «юзер+папка» — она **авто-резюмится**
   (`options.resume = session_id`), чтобы Claude помнил контекст диалога.
4. **Стриминг.** CLI отдаёт поток JSON-сообщений (`assistant`, `tool_use`, `result`, частичные дельты).
   Бот парсит их и **редактирует одно сообщение в чате в реальном времени** (черновики каждые ~0.3с,
   `ENABLE_STREAM_DRAFTS`).
5. **Результат.** В конце — финальный текст. Любые файлы, которые Claude создал/изменил в рабочей
   папке за ход, **авто-отправляются в чат** как документы (PDF, PNG, ZIP и т.д.).

Ключевой момент: **бот не дёргает Anthropic API напрямую** — он именно запускает локальный
`claude` CLI. Поэтому аутентификация берётся из самого Claude Code: достаточно один раз
сделать `claude login` (по подписке Claude). API-ключ не обязателен.

---

## 2. Что должно быть установлено (prerequisites)

| Компонент | Зачем | Установка |
|---|---|---|
| **Claude Code** (`claude`) | то, чем рулит бот | `npm i -g @anthropic-ai/claude-code` (или см. офиц. инсталлятор). Проверь: `which claude` → обычно `/opt/homebrew/bin/claude` |
| Залогиниться в Claude | аутентификация | `claude login` (один раз, в терминале от того же пользователя, под которым крутится бот) |
| **Python 3.11+** | язык бота | `brew install python@3.11` |
| **Poetry** | менеджер зависимостей бота | `pipx install poetry` или `pip3 install --user poetry` |
| **Telegram-бот** | свой токен | создать у [@BotFather](https://t.me/BotFather) → `/newbot` → получить `TELEGRAM_BOT_TOKEN` |
| Свой Telegram user id | белый список | узнать у [@userinfobot](https://t.me/userinfobot) → число для `ALLOWED_USERS` |

Сам бот — это форк `github.com/richardatkinson/claude-code-telegram` с доработками (режимы прав,
форвард файлов, TodoWrite-зеркало, проектные треды). Возьми исходники бота (попроси у меня
архив репозитория или склонируй ту версию, что крутится у меня — папка `~/claude-code-telegram-v2`).

---

## 3. Установка по шагам

### Шаг 1. Положить исходники бота
```bash
# распакуй/склонируй бота, например в:
cd ~
# git clone <repo> claude-code-telegram-v2   # или распакуй архив
cd ~/claude-code-telegram-v2
```

### Шаг 2. Поставить зависимости
```bash
cd ~/claude-code-telegram-v2
poetry install
# проверка, что точка входа есть:
poetry run claude-telegram-bot --help 2>/dev/null || echo "ок, запустим ниже"
```

### Шаг 3. Создать рабочую папку, где Claude будет работать
```bash
mkdir -p ~/my-claude-workspace
# (по желанию) положи туда CLAUDE.md со своими правилами — бот подмешает его в контекст
```

### Шаг 4. Настроить `.env`
Создай `~/claude-code-telegram-v2/.env` (скопируй из `.env.example` и заполни). Минимум:

```dotenv
# --- обязательное ---
TELEGRAM_BOT_TOKEN=123456:ABC...           # токен от @BotFather
TELEGRAM_BOT_USERNAME=@your_bot            # username твоего бота
APPROVED_DIRECTORY=/Users/ВАШ_ЮЗЕР/my-claude-workspace   # корень, дальше него бот не пускает
ALLOWED_USERS=277498593                    # твой telegram id (через запятую, если несколько)
CLAUDE_CLI_PATH=/opt/homebrew/bin/claude   # путь к бинарю claude (which claude)

# --- модель и лимиты ---
CLAUDE_MODEL=claude-opus-4-8               # модель Claude Code (опционально)
CLAUDE_MAX_TURNS=50
CLAUDE_MAX_COST_PER_REQUEST=5              # стоп-кран по $ на один запрос

# --- хранилище сессий бота (НЕ память Claude, а его собственная БД диалогов) ---
DATABASE_URL=sqlite:///data/bot_v2.db

# --- стриминг ответа в чат ---
ENABLE_STREAM_DRAFTS=true
STREAM_DRAFT_INTERVAL=0.3
VERBOSE_LEVEL=1

# --- проектные треды (опционально, можно выключить) ---
ENABLE_PROJECT_THREADS=false
```

> Важно: `APPROVED_DIRECTORY` — это «песочница». Бот разрешает Claude работать только внутри неё
> (и подпапок). Поставь сюда свою рабочую папку, а не весь диск.

### Шаг 5. Первый запуск вручную (проверка)
```bash
cd ~/claude-code-telegram-v2
poetry run claude-telegram-bot
```
Открой чат со своим ботом в Telegram:
```
/start
/status        → покажет рабочую папку и режим
напиши: "создай файл hello.txt с текстом привет"
```
Должно: появиться «печатает…», стримящийся ответ, и файл прилетит документом в чат.
Останови `Ctrl+C`.

Если ошибка аутентификации — значит Claude Code не залогинен: сделай `claude login` под тем же
пользователем и повтори.

---

## 4. Запуск 24/7 как сервис (launchd, macOS)

Чтобы бот сам поднимался при старте и перезапускался при падении — заверни его в `launchd`.

Создай файл `~/Library/LaunchAgents/com.you.telegram.bot.plist`
(замени `ВАШ_ЮЗЕР` на своё имя пользователя, проверь путь к poetry через `which poetry`):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.you.telegram.bot</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>-lc</string>
        <string>cd /Users/ВАШ_ЮЗЕР/claude-code-telegram-v2 && poetry run claude-telegram-bot</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/Users/ВАШ_ЮЗЕР/.local/bin</string>
        <key>HOME</key>
        <string>/Users/ВАШ_ЮЗЕР</string>
    </dict>
    <key>WorkingDirectory</key>
    <string>/Users/ВАШ_ЮЗЕР/claude-code-telegram-v2</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/telegram-bot.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/telegram-bot-error.log</string>
</dict>
</plist>
```

Загрузить и проверить:
```bash
launchctl load ~/Library/LaunchAgents/com.you.telegram.bot.plist
launchctl list | grep telegram          # должен быть в списке
tail -f /tmp/telegram-bot.log           # смотрим логи старта
```

Управление:
```bash
# остановить
launchctl unload ~/Library/LaunchAgents/com.you.telegram.bot.plist
# запустить заново
launchctl load   ~/Library/LaunchAgents/com.you.telegram.bot.plist
# перезапустить процесс
launchctl kickstart -k gui/$(id -u)/com.you.telegram.bot
```

> На одном `TELEGRAM_BOT_TOKEN` может крутиться только ОДИН long-poll. Не запускай руками и через
> launchd одновременно — будет конфликт. Перед ручным запуском делай `unload`.

---

## 5. Команды в чате (что умеет бот)

| Команда | Что делает |
|---|---|
| `/start`, `/status` | старт / текущая папка и режим |
| `/new` | сбросить сессию (Claude забудет диалог) и вернуться в корневую папку |
| `/safe` | спрашивать перед правками (по умолчанию) |
| `/accept` | авто-правки, но спрашивать про bash (`acceptEdits`) |
| `/plan` | режим только-чтение (`plan`) |
| `/yolo` | без подтверждений (`bypassPermissions`) — осторожно |

Эти режимы — это `permission_mode`, который бот передаёт в Claude Code CLI на каждый запуск.

---

## 6. Шпаргалка диагностики

| Симптом | Причина / решение |
|---|---|
| Бот молчит в чате | твой id не в `ALLOWED_USERS`; или процесс не запущен (`launchctl list`) |
| `CLINotFoundError` / claude не найден | неверный `CLAUDE_CLI_PATH`; проверь `which claude` |
| Ошибки авторизации Claude | сделай `claude login` под тем же пользователем, что и бот |
| `Conflict: terminated by other getUpdates` | бот запущен дважды на одном токене — оставь одну копию |
| Файлы не прилетают в чат | файл создан вне `APPROVED_DIRECTORY` или глубже 4 уровней вложенности |
| Смотреть, что происходит | `tail -f /tmp/telegram-bot.log` и `/tmp/telegram-bot-error.log` |

---

## 7. Что тут НЕ включено (и почему)

Это сознательно **чистый** слой «чат ↔ CLI». Сюда **не** входят и настраиваются отдельно под себя:

- личность/правила агента (`CLAUDE.md`, workspace-файлы) — положи свои в рабочую папку;
- система памяти/знаний (gbrain, MCP-серверы) — подключается отдельно через `ENABLE_MCP`/`MCP_CONFIG_PATH`;
- платёжные прокси и кошельки для эмбеддингов — это часть памяти, не часть бота;
- любые мои данные/проекты.

Получив этот слой, ты получаешь рабочего телеграм-бота, который гоняет Claude Code в твоей папке.
Дальше навешиваешь своё.
