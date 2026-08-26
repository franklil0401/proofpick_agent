"""
DTR Framework - Logging Utilities

Independent logging system with colored output and file support.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

__all__ = ["logger", "setup_logger", "progress"]

# ANSI color codes
COLORS = {
    'DEBUG': '\033[0;36m',    # Cyan
    'INFO': '\033[0;32m',     # Green
    'WARNING': '\033[0;33m',  # Yellow
    'ERROR': '\033[0;31m',    # Red
    'CRITICAL': '\033[0;35m', # Magenta
    'RESET': '\033[0m'        # Reset
}


class ColoredFormatter(logging.Formatter):
    """Formatter with color support"""
    
    def format(self, record):
        formatted = super().format(record)
        color = COLORS.get(record.levelname)
        if color and sys.stdout.isatty():  # Only color if terminal supports it
            return f"{color}{formatted}{COLORS['RESET']}"
        return formatted


def setup_logger(
    name: str = "DTR",
    level: int = logging.INFO,
    log_file: Optional[str] = None,
    log_dir: Optional[str] = None
) -> logging.Logger:
    """
    Setup and return a logger instance
    
    Args:
        name: Logger name
        level: Logging level
        log_file: Optional specific log file path
        log_dir: Optional log directory (auto-generates filename)
        
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.handlers.clear()
    logger.propagate = False
    
    # Console handler with colors
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    formatter = ColoredFormatter(
        fmt='[%(asctime)s] %(levelname)-8s %(name)s - %(message)s',
        datefmt='%H:%M:%S'
    )
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File handler
    if log_file or log_dir:
        if log_dir:
            Path(log_dir).mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            log_file = str(Path(log_dir) / f"dtr_{timestamp}.log")
        
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(level)
        file_formatter = logging.Formatter(
            fmt='[%(asctime)s] %(levelname)-8s %(name)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
        logger.info(f"Logging to file: {log_file}")
    
    return logger


# Default logger instance
logger = setup_logger()


def progress(stage: str, message: str, *, done: Optional[bool] = None):
    """
    Log progress with stage indicator
    
    Args:
        stage: Stage/category name
        message: Progress message
        done: Optional completion flag (True=✅, False=❌)
    """
    suffix = ""
    if done is True:
        suffix = " ✅"
    elif done is False:
        suffix = " ❌"
    logger.info(f"[{stage}] {message}{suffix}")


if __name__ == "__main__":
    # Test logger
    logger.debug("Debug message")
    logger.info("Info message")
    logger.warning("Warning message")
    logger.error("Error message")
    
    progress("TEST", "Starting test")
    progress("TEST", "Test completed", done=True)
    progress("TEST", "Test failed", done=False)

