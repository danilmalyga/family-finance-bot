# Family Finance Assistant MVP

Telegram-бот и REST API для семейного учёта финансов двух участников одной семьи. Операции сохраняются в PostgreSQL, автор каждой операции фиксируется, расчёты бюджета выполняет Python-код, а OpenAI используется только для разбора текста/чеков и человекочитаемого объяснения покупки.

## Архитектура

- `app/bot` — Telegram handlers, keyboards, FSM, middleware.
- `app/api` — REST API с `X-API-Key`.
- `app/services` — бизнес-логика, `BudgetEngine`, обработка операций и чеков.
- `app/repositories` — доступ к PostgreSQL.
- `app/db/models` и `app/db/migrations` — SQLAlchemy 2 модели и Alembic.
- `app/integrations` — OpenAI SDK.
- `app/prompts` — системные промпты.
- `tests` — тесты финансовой логики и OpenAI/receipt parsing.

## Требования

- Docker и Docker Compose.
- Telegram bot token.
- OpenAI API key и модель в `OPENAI_MODEL`.
- Python 3.11+ для локального запуска без Docker.

## Telegram BotFather

1. Откройте Telegram и найдите `@BotFather`.
2. Отправьте `/newbot`.
3. Задайте имя и username бота.
4. Скопируйте token в `.env` как `TELEGRAM_BOT_TOKEN`.

## Как узнать Telegram user ID

Напишите `@userinfobot` или `@RawDataBot` в Telegram и скопируйте свой numeric ID. Для двух участников укажите:

```env
ALLOWED_TELEGRAM_USER_IDS=111111111,222222222
```

## Настройка

```bash
cp .env.example .env
```

Заполните:

```env
TELEGRAM_BOT_TOKEN=...
ALLOWED_TELEGRAM_USER_IDS=111111111,222222222
OPENAI_API_KEY=...
OPENAI_MODEL=...
API_SECRET_KEY=local-secret
```

## Запуск через Docker Compose

```bash
docker compose up --build
```

Контейнер `app` ждёт готовности PostgreSQL, применяет миграции и запускает FastAPI. Telegram polling стартует внутри приложения, если указан `TELEGRAM_BOT_TOKEN`.

## Миграции

В Docker миграции применяются автоматически. Вручную:

```bash
alembic upgrade head
```

## Seed

Seed создаёт семью `Family`, категории, бюджет на текущий месяц, обязательный долг 650 €, жильё и коммунальные услуги 1000 €, резерв 1500 € и цель накоплений 300 €.

```bash
python -m scripts.seed
```

## Тесты и проверки

```bash
pytest
ruff check .
mypy .
```

Тесты OpenAI используют mocks/локальную JSON-валидацию и не вызывают реальный API.

## Использование бота

Команды:

```text
/start
/help
/balance
/month
/categories
/planned
/wishlist
/goals
/settings
```

Главное меню:

```text
❤️ Список желаний | 📷 Отправить чек
📊 Отчёт          | ➕ Добавить расход
📈 Инфографика    | 🛒 Можно ли купить?
⚙️ Настройки
```

Примеры сообщений:

```text
Mercadona 38.40
Потратил 18 евро на такси
75 евро занятия ребёнка
+3400 зарплата
Парфюм 140 евро
```

После распознавания операция создаётся как `draft` и не влияет на бюджет до нажатия `Подтвердить`.

В `⚙️ Настройки`:

- `План зарплатного цикла`: `3400 300 1500 10`, где `10` — день зарплаты. Это план, а не фактический доход.
- `Зарплата пришла`: создаёт подтверждённый доход на сумму из плана текущего зарплатного цикла.
- `Бюджет продуктов на неделю`: `200 вторник`. В отчёте будет показано, сколько из недельного лимита продуктов осталось до следующего вторника.
- Расширенный формат бюджета одной строкой: `3400 300 1500 10 200 вторник`.

## API

Передавайте ключ:

```bash
curl -H "X-API-Key: local-secret" http://localhost:8000/health
```

Маршруты:

- `GET /health`
- `GET /api/v1/transactions`
- `POST /api/v1/transactions`
- `GET /api/v1/transactions/{id}`
- `PATCH /api/v1/transactions/{id}`
- `DELETE /api/v1/transactions/{id}`
- `GET /api/v1/budgets/current`
- `PUT /api/v1/budgets/current`
- `GET /api/v1/reports/monthly`
- `POST /api/v1/purchase-advice`
- `GET /api/v1/wishlist`
- `POST /api/v1/wishlist`
- `PATCH /api/v1/wishlist/{id}?status=purchased`
- `GET /api/v1/recurring-payments`
- `POST /api/v1/recurring-payments`
- `PATCH /api/v1/recurring-payments/{id}?is_active=false`
- `DELETE /api/v1/recurring-payments/{id}`

## Инфографика

После запуска откройте в браузере:

```text
http://localhost:8000/dashboard?key=local-secret
```

Где `local-secret` — значение `API_SECRET_KEY` из `.env`.

Страница показывает:

- реальный остаток;
- доступно к тратам;
- расходы периода;
- безопасный дневной лимит;
- обязательные платежи до конца финансового периода;
- категории расходов;
- последние подтверждённые операции;
- черновики, которые ещё не попали в отчёт.

В Telegram ссылку можно получить командой:

```text
/dashboard
```

## Перенос на сервер

Сейчас приложение работает на вашем MacBook. Если MacBook выключен или Docker Desktop остановлен, Telegram-бот и dashboard не работают.

Для постоянной работы перенесите проект на сервер:

1. Возьмите VPS или PaaS-хостинг, где можно запускать Docker Compose.
2. Скопируйте проект на сервер.
3. Создайте `.env` на сервере.
4. Укажите production-секреты и новый `DATABASE_URL`, если PostgreSQL будет внешним.
5. Запустите:

```bash
docker compose up --build -d
```

Для базы можно использовать:

- PostgreSQL в этом же `docker-compose.yml`;
- Supabase PostgreSQL;
- managed PostgreSQL у хостинга.

Если используете внешний PostgreSQL, замените:

```env
DATABASE_URL=postgresql+asyncpg://user:password@host:5432/dbname
```

Для публичного dashboard поставьте reverse proxy с HTTPS. В production не публикуйте dashboard без защиты; текущий MVP защищает его через `?key=API_SECRET_KEY`.

### Render.com + Supabase

Проект подготовлен для Render:

- `render.yaml` описывает Docker Web Service;
- `scripts/start.sh` использует `PORT`, который Render выдаёт автоматически;
- `DATABASE_SSL=true` включает SSL-подключение к Supabase;
- `PUBLIC_BASE_URL` используется ботом для ссылки на dashboard.

1. Создайте Supabase project.
2. В Supabase откройте `Project Settings` -> `Database` -> `Connection string`.
3. Для Render используйте `Session Pooler` или `Transaction Pooler`, а не `Direct connection`.
   Direct host вида `db.<project>.supabase.co:5432` может быть IPv6-only и на Render падать с `Network is unreachable`.
   Pooler обычно выглядит как `aws-0-REGION.pooler.supabase.com:6543`.
4. Преобразуйте URL:

```text
postgresql://... -> postgresql+asyncpg://...
```

5. Если пароль содержит спецсимволы, закодируйте их:

```text
! -> %21
? -> %3F
@ -> %40
# -> %23
% -> %25
```

Пример:

```env
DATABASE_URL=postgresql+asyncpg://postgres.PROJECT_REF:ENCODED_PASSWORD@aws-0-REGION.pooler.supabase.com:6543/postgres
DATABASE_SSL=true
```

6. Создайте GitHub repository и загрузите проект.
7. В Render создайте Blueprint или Web Service из repository.
8. Заполните Environment Variables:

```env
APP_ENV=production
APP_HOST=0.0.0.0
DATABASE_URL=postgresql+asyncpg://...
DATABASE_SSL=true
PUBLIC_BASE_URL=https://your-app.onrender.com
TELEGRAM_BOT_TOKEN=...
ALLOWED_TELEGRAM_USER_IDS=...
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4o-mini
API_SECRET_KEY=...
DEFAULT_CURRENCY=EUR
DEFAULT_TIMEZONE=Europe/Madrid
MAX_RECEIPT_SIZE_MB=10
LOG_LEVEL=INFO
```

8. После deploy откройте:

```text
https://your-app.onrender.com/health
https://your-app.onrender.com/dashboard?key=API_SECRET_KEY
```

Для MVP бот продолжает работать через Telegram polling внутри Web Service. Следующий production-шаг — перевести Telegram на webhook.

## Ограничения MVP

- Нет Telegram Mini App.
- Изменение суммы/категории/описания через inline-кнопки в MVP сообщает использовать API или повторное добавление; подтверждение и отклонение работают в боте.
- Настройки бюджета и обязательных платежей доступны через Telegram и API.
- Текущий доступный остаток рассчитывается как доходы минус расходы, накопления и долги без банковских счетов и начальных остатков.
- Idempotency update_id хранится в памяти процесса.

## Дальнейшее развитие

- Полные FSM-диалоги редактирования суммы, категории и описания.
- JWT и роли для REST API.
- Банковские счета и начальные остатки.
- Персональные категории семьи.
- Webhook вместо polling для production.
- Экспорт в CSV/XLSX и расширенная аналитика.
