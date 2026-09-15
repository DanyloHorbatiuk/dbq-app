# SQL Analytics Workbench

Вебзастосунок для виконання аналітичних SQL-запитів до PostgreSQL з вимірюванням
часу виконання, розбором планів і візуалізацією результатів.

Проєктно-технологічна практика, НУ «Львівська політехніка», кафедра АСУ.
Тема: «Аналіз та обробка даних у реляційних базах даних».

## Швидкий старт

```bash
cp .env.example .env          # заповнити паролі
cp /шлях/до/dvdrental.tar db/dvdrental/   # опційно, див. нижче
make up
```

- Інтерфейс: http://localhost:8000
- Swagger: http://localhost:8000/docs
- pgAdmin (опційно): `make tools` → http://localhost:5050

## Документи

| Файл | Призначення |
|---|---|
| `SPEC.md` | Технічне завдання: вимоги, API, критерії приймання |
| `CLAUDE.md` | Правила роботи над проєктом |
| `ROADMAP.md` | План реалізації по етапах |
| `TODO.md` | Відкладені пункти, які лишилось закрити |

## Структура проєкту

```
sql-analytics-workbench/
│
├── SPEC.md                       ТЗ
├── CLAUDE.md                     правила роботи над проєктом
├── ROADMAP.md                    план по етапах
├── TODO.md                       відкладені пункти (наразі: каталог dvdrental)
├── README.md
├── Makefile                      точки входу: up, reset, test, lint, bench, verify...
├── docker-compose.yml
├── requirements.txt
├── pytest.ini
├── .env.example                  шаблон конфігурації (.env не комітиться)
│
├── docker/
│   ├── Dockerfile.api            образ FastAPI-застосунку
│   ├── pgadmin/
│   │   └── servers.json          передреєстрований сервер для pgAdmin
│   └── postgres/
│       └── initdb/               виконуються один раз при створенні тому
│           ├── 10_roles.sh       ролі saw_admin, saw_readonly, museum_manager
│           ├── 20_databases.sh   бази museum + dvdrental, розширення
│           ├── 30_restore_dvdrental.sh
│           ├── 40_init_museum.sh застосування db/museum/*.sql
│           └── 50_grants.sh      права SELECT-only для saw_readonly
│
├── db/
│   ├── dvdrental/
│   │   └── dvdrental.tar         дамп (не в git — покласти вручну)
│   └── museum/
│       ├── legacy_schema.sql     початкова версія схеми, довідково
│       ├── 01_schema.sql         таблиці
│       ├── 02_constraints.sql    обмеження, зокрема два EXCLUDE USING gist
│       ├── 03_functions.sql      функції PL/pgSQL
│       ├── 04_views.sql          v_quarterly_sales_performance, mv_monthly_revenue
│       ├── 05_triggers.sql       аудит tickets/ticket_prices
│       ├── 06_seed_reference.sql довідники (зали, типи артефактів, персонал)
│       └── 07_generate_data.sql  генератор (≥300 тис. квитків, setseed(0.42))
│
├── queries/                      каталог запитів, один YAML — один запит
│   ├── dvdrental/level1/ … level4/    порожньо — див. TODO.md
│   └── museum/level1/ … level4/       34 запити, 100% покриття SQL_FEATURE_CHECKLIST
│
├── experiments/                  описи керованих експериментів з індексами
│   ├── idx-museum-*.yaml         5 індексних експериментів
│   └── view-vs-matview-*.yaml    VIEW проти MATERIALIZED VIEW
│
├── app/
│   ├── main.py                   збірка застосунку, lifespan, статика
│   ├── config.py                 конфігурація з оточення (pydantic-settings)
│   ├── db.py                     чотири пули з'єднань: (museum|dvdrental) × (readonly|admin)
│   ├── models.py                 Pydantic-моделі запитів і відповідей
│   ├── catalog.py                завантаження й валідація YAML-каталогу, покриття
│   ├── security.py               валідація довільного SQL (§ФВ-03)
│   ├── executor.py               виконання в READ ONLY транзакції, таймінги
│   ├── explain.py                EXPLAIN FORMAT JSON і розбір дерева плану
│   ├── benchmark.py               серія прогонів, статистика, environment
│   ├── experiments.py            завантаження experiments/*.yaml
│   ├── experiment_runner.py      виконання експериментів (єдиний користувач admin-пулу)
│   ├── routers/
│   │   ├── meta.py               health, server-info, schema, coverage
│   │   ├── catalog.py
│   │   ├── execute.py
│   │   ├── explain.py
│   │   ├── benchmark.py
│   │   └── experiments.py
│   └── static/                   HTML/CSS/vanilla JS, без збирача
│       ├── index.html
│       ├── styles.css
│       └── js/                   api, catalog, sql-console, experiments, schema,
│                                  results, charts, plan, util, main
│
├── scripts/
│   ├── verify.py                 оркестрація перевірки критеріїв приймання (SPEC.md §7)
│   ├── verify_checks.py          самі перевірки
│   ├── verify_report.py          акумулятор PASS/FAIL
│   └── run_all_benchmarks.py     прогін бенчмарків усього каталогу в reports/
│
├── tests/
│   ├── conftest.py                readonly_pool (museum), catalog fixtures
│   ├── test_security.py          негативні тести на довільний SQL
│   ├── test_executor.py
│   ├── test_explain.py
│   ├── test_benchmark.py
│   ├── test_catalog.py           валідність YAML, унікальність id, покриття
│   └── test_catalog_runs.py      кожен запит каталогу (+ варіанти) виконується
│
└── reports/                      генерується кодом, іде у звіт — не редагувати вручну
    ├── benchmarks.csv
    ├── index_experiments.csv
    ├── catalog_coverage.csv
    ├── table_sizes.csv
    └── plans/*.json
```

## Тестування та перевірка критеріїв приймання

```
make test      # pytest: ≥25 тестів, покриває executor/explain/benchmark/security/catalog
make lint      # ruff check + ruff format --check
make bench     # прогнати бенчмарк кожного запиту каталогу (і кожного варіанта) → reports/benchmarks.csv
make verify    # перевірка всіх критеріїв приймання SPEC.md §7, з живою базою
```

`make verify` ганяє живу перевірку (не заглушки): реально виконує кожен запит
каталогу, реально прогонює всі 5 індексних експериментів (до/після, зміна вузла
доступу в плані), реально рахує рядки в таблицях museum. Він **чесно повертає
код виходу 1**, якщо якийсь критерій не пройдено — станом на зараз це два пункти,
що напряму залежать від порожнього каталогу `dvdrental` (див. `TODO.md`):
розмір каталогу (мінімум 55 запитів, зараз 34 — усі в museum) і кількість
запитів 3-го рівня (мінімум 20, зараз 9). Каталог `museum` сам по собі відповідає
своїй частині вимог: 34 запити, 100% покриття можливостей SQL, 6 пар варіантів,
5 індексних експериментів зі зміною вузла доступу.

## Де взяти dvdrental.tar

Дамп не зберігається в репозиторії через розмір. Покласти файл у
`db/dvdrental/dvdrental.tar` і виконати `make reset`. Якщо файл відсутній,
стек усе одно підніметься, база `dvdrental` буде створена, але порожня —
про це повідомить лог контейнера `postgres`. Каталог запитів для `dvdrental`
з'явиться окремим кроком після цього — див. `TODO.md`.

## Безпека

Довільний SQL виконується під роллю `saw_readonly` (тільки `SELECT`),
у транзакції з `SET TRANSACTION READ ONLY` і встановленим `statement_timeout`.
Роль `saw_admin` використовується виключно для команд з файлів `experiments/*.yaml`,
які не приймаються від клієнта — клієнт передає лише `experiment_id`.
Паролі зберігаються тільки в `.env` (не комітиться; шаблон — `.env.example`).
