# Release Candidate Checklist (RC2)

Дата: 2026-03-04  
Статус: `RC2-ready` (без известных блокеров после автопрогона ниже)

## 1) Автопрогон RC2 Quality Gate
- [x] Smoke-набор RC2 (web + ingest + RAG + ops):
  - `.\venv\Scripts\python.exe -m unittest tests.test_rc2_quality_gate tests.test_web_core_smoke tests.test_dashboard_contract tests.test_dashboard_news_noise tests.test_api_chat_reliability tests.test_ingest_service tests.test_rag_service tests.test_api_auth_baseline`
  - Result: `Ran 33 tests ... OK`
- [x] Проверка компиляции измененных файлов:
  - `.\venv\Scripts\python.exe -m compileall -q app/api.py tests/test_rc2_quality_gate.py`
  - Result: `OK`

## 2) Что закрывает RC2 gate
- [x] Ingest:
  - `/signals` отдает `signals.v1` и валидную структуру источников.
  - Dashboard-слой продолжает поднимать `signals` без падений.
- [x] RAG:
  - `/gemma/message` корректно блокирует персональные запросы без источников.
  - Нет silent-failure: пользователь получает понятный ответ.
- [x] Ops:
  - `/ops/services` возвращает полный статус API/Ollama/security.
  - `/ops/ollama/restart` и `/ops/api/reload` обрабатываются без runtime-ошибок.

## 3) Ручной чек-лист RC2
- [ ] Открыть `/dashboard?token=<token>` с основного устройства.
- [ ] Проверить, что в `Сигнальном радаре` работают:
  - сохранение профиля шумов,
  - скрытие тем/источников,
  - блок `почему это показано`.
- [ ] Проверить ingest в UI:
  - карточка `Сигналы` показывает `enabled/status/count/sources`.
- [ ] Проверить RAG вручную через чат:
  - запрос по личным данным без источников -> защитное сообщение,
  - запрос с доступными источниками -> ответ с блоком `Источники`.
- [ ] Проверить ops-контур:
  - `Статус` отображает актуальные API/Ollama/security статусы,
  - `Ollama ↻` и `API ↻` дают понятный feedback в чате.

## 4) Security baseline для RC2
- [x] Рекомендуемые флаги:
  - `DASHBOARD_AUTH_ENABLED=1`
  - `DASHBOARD_ACCESS_TOKEN=<secret>`
  - `API_DEBUG_EVENTS=0`
  - `API_DEBUG_EVENTS_REMOTE=0`
- [x] Не включать публичный доступ по умолчанию:
  - `DASHBOARD_ALLOW_PUBLIC=0`

## 5) Блокеры
- Нет известных блокеров по результатам текущего RC2 автопогона.

## 6) Next (после RC2)
- Добавить один `scripts/rc2_gate.ps1` для запуска этого smoke-набора одной командой.
