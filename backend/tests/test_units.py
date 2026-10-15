from app.services.ingest import transcript_text
from app.services.redact import redact


def test_redact_removes_secrets_but_keeps_context():
    text = ("connect with postgres://admin:hunter2@db:5432/x and key AIzaSyA1234567890abcdefghijklmnopqrstu "
            "password=s3cretValue card 4111 1111 1111 1111")
    out, n = redact(text)
    assert "hunter2" not in out and "AIzaSy" not in out and "s3cretValue" not in out and "4111" not in out
    assert "postgres://" in out and n >= 4


def test_transcript_extracts_text_and_files():
    jsonl = "\n".join([
        '{"type":"user","message":{"role":"user","content":"Rename amount to net_amount"}}',
        '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Done."},'
        '{"type":"tool_use","name":"Edit","input":{"file_path":"/repo/models/stg_orders.sql"}}]}}',
        "not json",
    ])
    text, files = transcript_text(jsonl)
    assert "Rename amount to net_amount" in text
    assert files == ["/repo/models/stg_orders.sql"]
