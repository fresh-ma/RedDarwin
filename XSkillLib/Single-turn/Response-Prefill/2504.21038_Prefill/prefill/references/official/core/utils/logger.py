"""Logging configuration."""

import os
import logging
import sys
from datetime import datetime
from typing import Optional


def setup_logging(
    log_level: str = "INFO",
    log_dir: str = "logs",
    log_file: Optional[str] = None,
    console_output: bool = True
) -> logging.Logger:
    os.makedirs(log_dir, exist_ok=True)
    if log_file is None:
        log_file = f"experiment_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    log_path = os.path.join(log_dir, log_file)

    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    root = logging.getLogger()
    root.setLevel(getattr(logging, log_level.upper()))
    root.handlers.clear()

    fh = logging.FileHandler(log_path, encoding='utf-8')
    fh.setLevel(getattr(logging, log_level.upper()))
    fh.setFormatter(formatter)
    root.addHandler(fh)

    if console_output:
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(getattr(logging, log_level.upper()))
        ch.setFormatter(formatter)
        root.addHandler(ch)

    root.info(f"Logging initialized: {log_path}")
    return root
