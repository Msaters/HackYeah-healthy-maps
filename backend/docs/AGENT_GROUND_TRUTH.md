# Agent Ground Truth — Health Routes Backend

## Architektura
- **Brak bazy danych**: Stan w pamięci RAM (`MemoryStore`).
- **Auth**: Fake token, dependency `get_current_user`.
- **Routing**: Mock engine reagujący na `modes` (walk/bike) oraz `time_budget_minutes`.
- **HTTP Client**: Współdzielony `httpx.AsyncClient` w `lifespan`.
- **CORS**: Używa `allow_origin_regex=".*"` aby uniknąć błędów specyfikacji CORS przy `credentials=True`.
- **Config**: Oparty o `pydantic-settings` (BaseSettings).
