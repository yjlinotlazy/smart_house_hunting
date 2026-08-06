from __future__ import annotations

import logging
import re

_SECRET_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)(api[_-]?key|authorization)(\s*[:=]\s*)([^\s,&]+)"),
)


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        rendered = record.getMessage()
        for pattern in _SECRET_PATTERNS:
            if pattern.groups == 0:
                rendered = pattern.sub("[REDACTED]", rendered)
            else:
                rendered = pattern.sub(r"\1\2[REDACTED]", rendered)
        record.msg = rendered
        record.args = ()
        return True


def install_redaction(handlers: list[logging.Handler]) -> None:
    for handler in handlers:
        if not any(isinstance(item, RedactingFilter) for item in handler.filters):
            handler.addFilter(RedactingFilter())
