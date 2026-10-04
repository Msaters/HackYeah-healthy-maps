# Health Routes Backend

Backend dla aplikacji proponującej trasy (tryb demo / hackathon).

## Uruchomienie

```bash
python -m venv .venv
source .venv/bin/activate / .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --workers 1
```

Swagger: `http://127.0.0.1:8000/docs`
