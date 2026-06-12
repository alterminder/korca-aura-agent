# Testing

## Backend (ruff · mypy · pytest)

Tests live in `backend/tests/`. Run with:

```bash
cd backend
ruff check app       # lint
mypy app             # type check
pytest               # unit + integration tests
```

Pattern for async API tests:

```python
@pytest.mark.asyncio
async def test_upload_pdf(client, sample_pdf):
    response = await client.post(
        "/api/documents/upload",
        files={"file": ("test.pdf", sample_pdf, "application/pdf")}
    )
    assert response.status_code == 202
```

## Frontend

```bash
cd frontend
npm run typecheck
npm run lint
npm run build
```
