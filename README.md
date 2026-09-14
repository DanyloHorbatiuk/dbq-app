# SQL Analytics Workbench

Вебзастосунок для виконання аналітичних SQL-запитів до PostgreSQL з вимірюванням
часу виконання, розбором планів і візуалізацією результатів.

Проєктно-технологічна практика, НУ «Львівська політехніка», кафедра АСУ.
Тема: «Аналіз та обробка даних у реляційних базах даних».

## Швидкий старт

```bash
cp .env.example .env          # заповнити паролі
cp /шлях/до/dvdrental.tar db/dvdrental/
make up
```

- Інтерфейс: http://localhost:8000
- Swagger: http://localhost:8000/docs
- pgAdmin (опційно): `make tools` → http://localhost:5050

## Документи

| Файл | Призначення |
|---|---|
| `SPEC.md` | Технічне завдання: вимоги, API, критерії приймання |
| `CLAUDE.md` | Правила роботи для Claude Code |
| `ROADMAP.md` | План реалізації по етапах |

## Структура проєкту

```
sql-analytics-workbench/
│
├── SPEC.md                       ТЗ
├── CLAUDE.md                     інструкції для Claude Code
├── ROADMAP.md                    план по етапах
├── README.md
├── Makefile                      точки входу: up, reset, test, verify...
├── docker-compose.yml
├── requirements.txt
├── .env.example                  шаблон конфігурації (.env не комітиться)
│
├── docker/
│   ├── Dockerfile.api            образ FastAPI-застосунку
│   ├── pgadmin/
│   │   └── servers.json          передреєстрований сервер для pgAdmin
│   └── postgres/
│       └── initdb/               виконуються один раз при створенні тому
│           ├── 10_roles.sh       ролі saw_admin і saw_readonly
│           ├── 20_databases.sh   бази + розширення
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
│       ├── 02_constraints.sql    обмеження, зокрема EXCLUDE
│       ├── 03_functions.sql      функції PL/pgSQL
│       ├── 04_views.sql          представлення і матеріалізоване представлення
│       ├── 05_triggers.sql       аудит
│       ├── 06_seed_reference.sql довідники
│       ├── 07_generate_data.sql  генератор (≥300 тис. квитків, setseed)
│       ├── 08_indexes.sql        базові індекси
│       └── 09_grants.sql         права в межах схеми
│
├── queries/                      каталог запитів, один YAML — один запит
│   ├── dvdrental/
│   │   ├── level1/
│   │   ├── level2/
│   │   ├── level3/
│   │   └── level4/
│   └── museum/
│       ├── level1/ … level4/
│
├── experiments/                  описи експериментів з індексами
│   ├── idx-museum-tickets-date.yaml
│   └── ...
│
├── app/
│   ├── main.py                   збірка застосунку, lifespan, статика
│   ├── config.py                 конфігурація з оточення (pydantic-settings)
│   ├── db.py                     два пули з'єднань на базу: readonly / admin
│   ├── models.py                 Pydantic-моделі запитів і відповідей
│   ├── catalog.py                завантаження й валідація YAML-каталогу
│   ├── security.py               валідація довільного SQL
│   ├── executor.py               виконання в READ ONLY транзакції, таймінги
│   ├── explain.py                EXPLAIN FORMAT JSON і розбір дерева плану
│   ├── benchmark.py              серія прогонів, статистика, environment
│   ├── experiments.py            керовані експерименти з індексами
│   ├── export.py                 CSV і збереження планів
│   ├── routers/
│   │   ├── meta.py
│   │   ├── catalog.py
│   │   ├── execute.py
│   │   ├── explain.py
│   │   ├── benchmark.py
│   │   ├── experiments.py
│   │   └── stats.py              pg_stat_statements, розміри, невикористані індекси
│   └── static/
│       ├── index.html
│       ├── app.js                vanilla JS, без збирача
│       └── styles.css
│
├── scripts/
│   ├── verify.py                 перевірка критеріїв приймання (SPEC.md §7)
│   └── run_all_benchmarks.py     прогін усіх бенчмарків у reports/
│
├── tests/
│   ├── test_security.py          негативні тести на довільний SQL
│   ├── test_executor.py
│   ├── test_explain.py
│   ├── test_benchmark.py
│   ├── test_catalog.py           валідність усіх YAML, унікальність id
│   └── test_catalog_runs.py      кожен запит каталогу виконується
│
└── reports/                      генерується кодом, іде у звіт
    ├── benchmarks.csv
    ├── index_experiments.csv
    ├── catalog_coverage.csv
    ├── table_sizes.csv
    └── plans/*.json
```

## Де взяти dvdrental.tar

Дамп не зберігається в репозиторії через розмір. Покласти файл у
`db/dvdrental/dvdrental.tar` і виконати `make reset`. Якщо файл відсутній,
стек усе одно підніметься, але база `dvdrental` буде порожня — про це
повідомить лог контейнера `postgres`.

## Безпека

Довільний SQL виконується під роллю `saw_readonly` (тільки `SELECT`),
у транзакції `BEGIN READ ONLY`, зі встановленим `statement_timeout`.
Роль `saw_admin` використовується виключно для команд з файлів `experiments/*.yaml`,
які не приймаються від клієнта. Паролі зберігаються тільки в `.env`.
