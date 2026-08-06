import logging

from smart_house_hunting.logging_security import RedactingFilter


def test_log_filter_redacts_credentials() -> None:
    record = logging.LogRecord(
        "test", logging.INFO, "", 0, "Authorization: Bearer secret-token", (), None
    )
    assert RedactingFilter().filter(record)
    assert "secret-token" not in record.getMessage()
    assert "REDACTED" in record.getMessage()
