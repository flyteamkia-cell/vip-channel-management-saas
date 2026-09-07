import json
import logging
from datetime import UTC, datetime


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "funcName": record.funcName,
        }
        if hasattr(record, "tenant_id"):
            log_obj["tenant_id"] = str(record.tenant_id)
        return json.dumps(log_obj)


def setup_logger() -> logging.Logger:
    logger = logging.getLogger("vip_saas")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
    return logger

logger = setup_logger()
