# Карта модулей проекта

## 1. Что это за проект

Проект представляет собой Telegram-бота для прогнозов на турниры по настольному теннису. Основные пользовательские сценарии:

- регистрация через `/start`;
- просмотр актуальных турниров и создание прогноза;
- просмотр своих и чужих прогнозов;
- просмотр личной статистики и рейтингов;
- отправка баг-репортов.

Отдельно реализован административный контур:

- создание и публикация турниров;
- управление участниками турниров;
- управление глобальным списком игроков;
- ввод результатов турнира;
- пересчет очков, обновление агрегированной статистики и рассылка уведомлений.

Проект написан на `aiogram 3`, использует `SQLAlchemy Async`, `PostgreSQL`, `Redis`, `APScheduler`, `Pillow` и `Alembic`.

## 2. Основные точки входа

| Точка входа | Назначение | Что запускает |
| --- | --- | --- |
| `main.py` | Главный runtime entrypoint | Создает `Bot` и `Dispatcher`, подключает middleware и routers, запускает polling и weekly scheduler |
| `app/scripts/migrate_seasons.py` | Сезонное обслуживание и backfill | Создает/обновляет `Season` и `SeasonResult` по турнирам |
| `app/scripts/migrate_sqlite_to_pg.py` | Разовая миграция данных | Переносит данные из `app1.db` в PostgreSQL |
| `alembic/env.py` + `alembic/versions/*` | Основной контур schema-миграций | Применяет Alembic-миграции к текущей схеме |
| `download.py` | Отдельная CLI-утилита | Скачивает Telegram-файлы по `file_id` |
| `.github/workflows/deploy.yml` | Deployment entrypoint | Делает `git pull`, `docker compose up -d --build`, затем `alembic upgrade head` |
| `cloudflare_worker/wrangler.toml` | Контур внешнего worker/gateway | Описывает Cloudflare Worker и R2 bucket для временных медиа |

## 3. Жизненный цикл приложения

### Startup

1. `main.py` читает настройки из `app/config.py`.
2. Создается `Bot`; при наличии `tg_api_server` используется кастомный Telegram API server.
3. Поднимается FSM storage:
   - сначала `RedisStorage`;
   - при проблемах с записью - fallback на `MemoryStorage`.
4. Создается `Dispatcher`.
5. Подключается `AuthMiddleware` для `message` и `callback_query`.
6. Регистрируются роутеры в порядке:
   `admin` -> `feedback` -> `tournament_management` -> `player_management` -> `pagination` -> `prediction` -> `stats` -> `common`.
7. Вызываются `init_db()` и `migrate_seasons()`.
8. Поднимается `AsyncIOScheduler` с еженедельным вызовом `scheduled_season_rotation()`.
9. Удаляется webhook и запускается polling.

### Пользовательский сценарий

- Пользователь проходит через `/start`, получает запись в таблице `users` и reply-меню.
- Все последующие сценарии проходят через `AuthMiddleware`, который:
  - не пускает незарегистрированных пользователей;
  - синхронизирует `full_name` и `username` с Telegram.
- Для создания прогноза используются FSM-состояния `MakeForecast`.

### Административный сценарий

- Вход в админ-контур идет через `/admin`, `/manage_tournaments` и `/players`.
- Контур делится на два крупных домена:
  - управление турнирами и результатами;
  - управление глобальным каталогом игроков.
- После ввода результатов выполняется массовый пересчет очков прогнозов и пользовательской статистики.

### Фоновое обслуживание

- `APScheduler` раз в неделю вызывает `app/core/scheduler_tasks.py`.
- `scheduled_season_rotation()` делегирует работу `app/scripts/migrate_seasons.py`.

### Медиа и рендеринг

- `app/handlers/stats.py` готовит данные рейтинга/профиля.
- `app/utils/formatting.py` собирает текстовые блоки для рейтингов, профиля и детальной статистики.
- Статистика и рейтинги теперь отправляются как HTML-текст, без генерации PNG и без фото-транспорта.
- `app/utils/telegram_media.py` остался только для прочих медиа-сценариев вне stats-flow.

## 4. Верхнеуровневая карта каталогов

| Каталог / файл | Роль в системе | Комментарий |
| --- | --- | --- |
| `app/` | Основной код приложения | Внутри лежат handlers, data layer, utils, FSM, UI и core-логика |
| `alembic/` | Актуальный контур миграций БД | Использует `Base.metadata` из `app/db/models.py` |
| `tests/` | Автотесты util/data-слоя | Фокус на streaks, leaderboard snapshots, stats formatting и media helpers |
| `cloudflare_worker/` | Конфигурация внешнего worker | В репозитории есть `wrangler.toml`, но нет `src/index.js` |
| `fonts/` | Статические assets | Сейчас не участвуют в stats-flow |
| `logo.png` | Статический asset | Сейчас не участвует в stats-flow |
| `project-analysis/` | Архив ранее собранной аналитики | Не участвует в runtime |
| `main.py` | Главный процесс бота | Точка старта runtime |
| `Dockerfile`, `docker-compose.yml` | Контейнерный запуск | Поднимают `bot`, `db`, `redis` |
| `.github/workflows/deploy.yml` | CI/CD deployment path | Автодеплой по push в `main` |
| `download.py` | Отдельная операционная утилита | Не встроена в штатный runtime |
| `app1.db`, `dump.sql` | Исторические data-артефакты | Связаны с legacy/migration контуром |

## 5. Карта модулей внутри `app/`

Пустые `__init__.py` не перечислены отдельно: они выполняют роль package marker и не содержат собственной логики.

### 5.1. Конфигурация и access control

| Модуль | Назначение | Ключевые элементы | Основные зависимости |
| --- | --- | --- | --- |
| `app/config.py` | Центральная конфигурация приложения | `Settings`, `config`, parsing `admin_ids` | `.env`, `pydantic-settings` |
| `app/middlewares/auth.py` | Регистрационный и identity-gate для всех сценариев | `AuthMiddleware.__call__` | `async_session`, `User` |
| `app/filters/is_admin.py` | Админский фильтр | `IsAdmin` | `config.admin_ids` |
| `app/lexicon/ru.py` | Текстовые константы UI | `LexiconRU`, `LEXICON_RU` | Используется handlers и keyboards |

### 5.2. Data layer (`app/db/`)

| Модуль | Назначение | Ключевые сущности / функции | Кто использует |
| --- | --- | --- | --- |
| `app/db/models.py` | Главная ORM-схема | `User`, `Player`, `Tournament`, `Forecast`, `BugReport`, `Season`, `SeasonResult`, `TournamentStatus`, `tournament_participants` | Runtime, scripts, Alembic |
| `app/db/session.py` | Асинхронный engine и фабрика сессий | `engine`, `async_session`, `init_db()` | Все handlers, scripts, middleware |
| `app/db/crud.py` | Переиспользуемые запросы и CRUD-хелперы | `get_open_tournaments`, `get_forecast_for_editing`, `get_forecasts_by_date`, `create_forecast`, `create_bug_report`, `delete_forecast` | `prediction.py`, `feedback.py`, `leaderboard_data.py`, `view_helpers.py` |
| `app/db/migration_v1.py` | Legacy ручная миграция | schema patch | Legacy maintenance |
| `app/db/migration_v2_user.py` | Legacy ручная миграция | schema patch user-related | Legacy maintenance |
| `app/db/migration_v3_stats.py` | Legacy ручная миграция | schema patch stats-related | Legacy maintenance |
| `app/db/migration_v4_seasons.py` | Legacy ручная миграция | schema patch seasons-related | Legacy maintenance |
| `app/db/migration_v5_streaks.py` | Legacy ручная миграция | schema patch streak-related | Legacy maintenance |
| `app/db/migration_v6_max_streak.py` | Legacy ручная миграция | schema patch max-streak-related | Legacy maintenance |

Ключевые доменные сущности:

- `User` - пользователь Telegram и его накопленная статистика.
- `Player` - игрок, которого можно добавлять в турниры.
- `Tournament` - турнир со статусом, участниками, количеством слотов прогноза и фактическими результатами.
- `Forecast` - прогноз пользователя на конкретный турнир.
- `Season` / `SeasonResult` - недельные сезоны и их исторические снимки.
- `BugReport` - пользовательский отчет об ошибке.

### 5.3. Core-логика (`app/core/`)

| Модуль | Назначение | Ключевые функции | Кто использует |
| --- | --- | --- | --- |
| `app/core/scoring.py` | Правила подсчета очков и aggregate-метрик | `calculate_forecast_points`, `calculate_new_stats` | `tournament_management.py`, `leaderboard_data.py` |
| `app/core/seasonal.py` | Календарная логика сезонов | `get_season_dates`, `get_season_number`, `get_current_season_number` | `stats.py`, `migrate_seasons.py` |
| `app/core/scheduler_tasks.py` | Scheduler-wrapper | `scheduled_season_rotation` | `main.py` |

Здесь живет чистая доменная логика:

- scoring-контракт `+1 / +5 / +15`;
- вычисление `diffs`, `exact_hits`, `accuracy`, `MAE`;
- определение номера сезона от anchor-даты `2024-12-30`.

### 5.4. Пользовательские и административные handlers (`app/handlers/`)

| Модуль | Роль | Главные сценарии | Ключевые зависимости |
| --- | --- | --- | --- |
| `app/handlers/admin.py` | Точка входа в админ-панель | `/admin` | `IsAdmin`, `admin_menu_kb`, `TournamentManagement` |
| `app/handlers/common.py` | Общие пользовательские сценарии | `/start`, help, архив прогнозов, история, просмотр активного/исторического прогноза | `User`, `Tournament`, `Forecast`, `Player`, `inline.py`, `reply.py`, `formatting.py` |
| `app/handlers/prediction.py` | Основной forecast flow | выбор турнира, состав, сбор прогноза по шагам, сохранение/редактирование, просмотр чужих прогнозов | `crud.py`, `Forecast`, `User`, `MakeForecast`, `view_helpers.py`, `inline.py`, `LEXICON_RU` |
| `app/handlers/stats.py` | Статистика и рейтинги | профиль игрока, сезонный рейтинг, глобальный рейтинг, рейтинг дня, история сезонов, детальная сезонная таблица | `seasonal.py`, `leaderboard_data.py`, `stats_calculator.py`, `formatting.py` |
| `app/handlers/feedback.py` | FSM для баг-репортов | `/bug`, ввод описания, optional screenshot, запись и форвард в bug chat | `BugReport`, `crud.py`, `BugReportState`, `config.bug_report_chat_id` |
| `app/handlers/tournament_management.py` | Главный write-heavy админский модуль | создание турниров, публикация, список участников, изменение состава, ввод результатов, рассылки, пересчет статистики | `Tournament`, `Player`, `Forecast`, `User`, `TournamentManagement`, `SetResults`, `scoring.py`, `broadcaster.py` |
| `app/handlers/player_management.py` | Управление глобальным справочником игроков | список активных/архивных, добавление, переименование, изменение рейтинга, архивирование/восстановление | `Player`, `PlayerManagement`, `inline.py`, `IsAdmin` |
| `app/handlers/view_helpers.py` | Общий helper для карточки прогноза | `show_forecast_card` | `crud.py`, `view_forecast_kb` |
| `app/handlers/pagination.py` | Общая пагинация списков игроков | `cq_paginate_players`, `cq_noop` | `FSMContext`, `get_paginated_players_kb` |

Наиболее важные orchestration-модули:

- `app/handlers/prediction.py` - управляет пользовательским жизненным циклом прогноза.
- `app/handlers/tournament_management.py` - управляет жизненным циклом турнира и write-path после публикации результатов.
- `app/handlers/stats.py` - главный read/render-path для рейтингов и текстовой статистики.

### 5.5. UI, FSM и callback contracts

| Модуль | Назначение | Что содержит |
| --- | --- | --- |
| `app/keyboards/inline.py` | Центральный фабричный слой inline-клавиатур | выбор турнира, пагинация игроков и турниров, history menus, admin menus, прогнозы участников, help |
| `app/keyboards/reply.py` | Главное reply-меню пользователя | кнопки актуальных турниров, рейтинга, статистики, архива и правил |
| `app/states/user_states.py` | FSM для пользовательских сценариев | `MakeForecast`, `BugReportState`, `LeaderboardState` |
| `app/states/tournament_management.py` | FSM для админского управления турнирами | `TournamentManagement`, `SetResults` |
| `app/states/player_management.py` | FSM для каталога игроков | `PlayerManagement` |

Этот слой особенно важен, потому что строковые callback namespace являются контрактом между keyboards и handlers:

- `view_forecast:*`
- `vof_*`
- `tm_*`
- `pm_*`
- `leaderboard:*`
- `help:*`

### 5.6. Utilities (`app/utils/`)

| Модуль | Назначение | Ключевые функции | Кто использует |
| --- | --- | --- | --- |
| `app/utils/formatting.py` | Строковые helper-функции | `get_medal_str`, `format_player_list`, `get_user_rank`, `format_user_name`, `format_breadcrumbs`, `format_user_profile_text`, `format_leaderboard_entries`, `format_detailed_season_rows`, `split_text_chunks` | handlers, feedback, admin notifications |
| `app/utils/broadcaster.py` | Безопасная массовая рассылка | `broadcast_message` | `tournament_management.py` |
| `app/utils/stats_calculator.py` | Пересчет streak-метрик | `calculate_user_tournament_streaks`, `recalculate_user_streaks` | `stats.py`, потенциально write-flows |
| `app/utils/leaderboard_data.py` | Подготовка данных для daily/season stats | `build_daily_leaderboard_snapshot`, `build_detailed_season_snapshot` | `stats.py` |
| `app/utils/telegram_media.py` | Надежная доставка изображений в Telegram | `send_photo_with_retry`, `edit_message_photo_with_retry`, `send_or_update_photo` | media-oriented flows |
| `app/utils/temp_media.py` | Временная публикация и удаление медиа | `upload_temp_media`, `delete_temp_media`, `schedule_temp_media_delete` | `telegram_media.py` |

По факту `app/utils/` делится на четыре подзоны:

- formatting helpers;
- data-preparation helpers для статистики;
- media delivery / временный media hosting.

### 5.7. Scripts (`app/scripts/`)

| Модуль | Назначение | Что делает |
| --- | --- | --- |
| `app/scripts/migrate_seasons.py` | Сезонный backfill и snapshotting | Находит турниры, вычисляет сезоны, создает `Season`, пишет `SeasonResult` |
| `app/scripts/migrate_sqlite_to_pg.py` | Перенос данных из SQLite в PostgreSQL | Копирует таблицы по порядку, парсит JSON/Date/DateTime, пытается восстановить sequence |

## 6. Карта зависимостей между ключевыми модулями

### Главная зависимостная цепочка

```text
main.py
  -> app.config
  -> app.db.session
  -> app.middlewares.auth
  -> app.handlers.admin
  -> app.handlers.feedback
  -> app.handlers.tournament_management
  -> app.handlers.player_management
  -> app.handlers.pagination
  -> app.handlers.prediction
  -> app.handlers.stats
  -> app.handlers.common
  -> app.core.scheduler_tasks
       -> app.scripts.migrate_seasons
```

### Основные прикладные связи

| Откуда | Куда | Зачем |
| --- | --- | --- |
| `app/handlers/prediction.py` | `app/db/crud.py` | Получение турниров, прогнозов и игроков |
| `app/handlers/prediction.py` | `app/handlers/view_helpers.py` | Повторное отображение карточки прогноза |
| `app/handlers/prediction.py` | `app/states/user_states.py` | FSM для создания прогноза |
| `app/handlers/tournament_management.py` | `app/core/scoring.py` | Подсчет очков и aggregate-статистики после ввода результатов |
| `app/handlers/tournament_management.py` | `app/utils/broadcaster.py` | Рассылки о новых турнирах и смене статуса |
| `app/handlers/stats.py` | `app/utils/leaderboard_data.py` | Сбор данных для daily/season snapshots |
| `app/handlers/stats.py` | `app/utils/stats_calculator.py` | Вычисление текущего и максимального streak |
| `app/handlers/stats.py` | `app/utils/formatting.py` | Сборка текстовых карточек, leaderboard blocks и chunking |
| `app/utils/leaderboard_data.py` | `app/db/crud.py` | Выборка прогнозов по дате |
| `app/utils/leaderboard_data.py` | `app/core/scoring.py` | Вычисление exact/perfect statistics |
| `app/utils/telegram_media.py` | `app/utils/temp_media.py` | Временная публикация изображения по URL |
| `alembic/env.py` | `app/db/models.py`, `app/config.py` | Получение `Base.metadata` и runtime `database_url` |

### Два самых важных бизнес-потока

#### 1. Поток пользовательского прогноза

`reply keyboard` -> `app/handlers/prediction.py` -> `app/db/crud.py` / `app/db/models.py` -> `FSM MakeForecast` -> сохранение `Forecast` -> обновление streak-полей пользователя.

#### 2. Поток завершения турнира

`app/handlers/tournament_management.py:cq_set_results_confirm()` -> обновление `Tournament.results` и `Tournament.status` -> подсчет очков через `app/core/scoring.py` -> обновление `Forecast.points_earned` и aggregate-полей `User` -> персональные уведомления и admin summary.

## 7. Внешние и операционные модули

| Модуль / файл | Роль | Примечание |
| --- | --- | --- |
| `alembic/env.py` | Runtime config для Alembic | Подтягивает `.env`, `Base.metadata`, `database_url` |
| `alembic/versions/f2c27d06c3bc_initial_migration_with_biginteger.py` | Текущий базовый schema snapshot | Создает основные таблицы и enum `tournamentstatus` |
| `Dockerfile` | Runtime image | `python:3.12-slim`, затем `python main.py` |
| `docker-compose.yml` | Локальный/серверный оркестратор | Поднимает `bot`, `db`, `redis`; migrations отдельно не запускает |
| `.github/workflows/deploy.yml` | Автодеплой | Сначала rebuild/restart, потом `alembic upgrade head` |
| `cloudflare_worker/wrangler.toml` | Внешний worker-контур | Есть R2 bucket и cron, но исходный JS entrypoint отсутствует |
| `download.py` | Сервисная утилита | Архитектурно не участвует в основном runtime |

## 8. Покрытие тестами

| Тест | Что покрывает |
| --- | --- |
| `tests/test_stats_calculator.py` | Логику streaks в `app/utils/stats_calculator.py` |
| `tests/test_leaderboard_data.py` | Сбор daily snapshot и detailed season snapshot |
| `tests/test_image_rendering.py` | Smoke/fallback-проверки генерации PNG |
| `tests/test_telegram_media.py` | Retry/edit/send path для `telegram_media.py` |
| `tests/test_temp_media.py` | Upload/delete path для `temp_media.py` |

Что видно по тестовой стратегии:

- util/data/rendering-слой покрыт заметно лучше, чем handlers;
- нет видимого автоматического покрытия FSM-потоков и callback-контрактов;
- нет выделенных тестов на `main.py`, middleware, admin lifecycle и Alembic/deploy path.

## 9. Архитектурные наблюдения и риски

### Подтвержденные особенности

1. `app/db/session.py:init_db()` сейчас фактически no-op: startup hook есть, но схему он не создает.
2. В проекте существуют два migration-контура:
   - актуальный через `alembic/`;
   - legacy/manual через `app/db/migration_v*.py`.
3. `app/scripts/migrate_seasons.py` не пересобирает `SeasonResult`, если для сезона записи уже есть; это ограничивает переиспользуемость скрипта как полного rebuild-инструмента.
4. `app/handlers/stats.py` является отдельным read/render-контуром со своей data-preparation и media-delivery цепочкой.
5. `app/utils/telegram_media.py` хорошо изолирует retry-логику и сценарий `send vs edit`.

### Наблюдаемые проблемные зоны

1. `app/keyboards/inline.py` содержит дублирующиеся определения `help_back_kb`, `add_player_success_kb` и `add_global_player_success_kb`; это повышает риск несогласованных правок.
2. В `app/handlers/tournament_management.py` установлен `router.message.filter(IsAdmin())`, но не установлен `router.callback_query.filter(IsAdmin())`; при этом в `player_management.py` callback-фильтр есть. Это выглядит как непоследовательная защита admin callback path.
3. `download.py` содержит standalone-утилиту с захардкоженным bot token в исходнике; такой файл лучше вынести из репозитория или перевести на env-конфигурацию.
4. `cloudflare_worker/wrangler.toml` ссылается на `src/index.js`, которого нет в репозитории; значит worker-контур описан не полностью.
5. `requirements.txt` заметно шире реально наблюдаемого runtime-кода; в проекте есть признаки накопленного dependency-шума.

### Что критично не ломать при изменениях

- callback namespaces из `app/keyboards/inline.py`;
- статусы `TournamentStatus.DRAFT`, `OPEN`, `LIVE`, `FINISHED`;
- scoring-контракт `+1 / +5 / +15`;
- сезонную anchor-дату и функции из `app/core/seasonal.py`;
- зависимости image rendering от `fonts/` и `logo.png`;
- поведение `AuthMiddleware` и список `admin_ids`.

## 10. Итоговая модульная картина

Проект удобно воспринимать как 7 логических контуров:

1. `runtime-bootstrap` - `main.py`, конфигурация, middleware, router wiring, scheduler.
2. `interaction-layer` - все handlers, keyboards, states и lexicon.
3. `data-layer` - ORM-модели, session factory и CRUD helpers.
4. `domain-core` - scoring и seasonal logic.
5. `stats-media` - snapshot builders, image rendering, telegram media delivery.
6. `maintenance-migration` - seasonal scripts, SQLite transfer, Alembic и legacy schema patches.
7. `infra-deployment` - Docker/Compose/GitHub Actions/Cloudflare worker config.

Самые нагруженные и чувствительные модули:

- `app/handlers/tournament_management.py` - главный write-path и orchestration центр административного контура.
- `app/handlers/prediction.py` - основной пользовательский сценарий создания прогнозов.
- `app/handlers/stats.py` - read-heavy контур статистики с рендерингом медиа.
- `app/db/models.py` - точка концентрации всей доменной схемы.
- `app/keyboards/inline.py` - единый callback contract layer для user/admin-навигации.

Если нужно развивать проект дальше, безопаснее всего планировать изменения не по каталогам, а по этим логическим контурам.
