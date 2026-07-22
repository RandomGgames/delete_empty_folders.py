"""
Delete Empty Folders

This script recursively scans specified directories and deletes any empty folders it finds. It supports configuration for which paths to scan, which paths to ignore (exact or partial matches), and logs all actions taken. Deleted folders are sent to the system recycle bin (using send2trash) for safety.

Usage:
    - Configure the script by editing the ScriptSettings dataclass or by loading settings from a config file if implemented.
    - Run the script directly: python delete_empty_folders.py
    - Logging and runtime behavior can be customized via LogSettings and RuntimeSettings.

Features:
    - Recursively deletes empty folders in user-specified locations
    - Skips folders based on exact or partial path matches
    - Sends deleted folders to the recycle bin
    - Detailed logging with configurable output
"""

import json
import logging
import logging.handlers
import os
import socket
import sys
import traceback
import typing
from dataclasses import dataclass, field
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from send2trash import send2trash

logger = logging.getLogger(__name__)

__version__ = "1.2.1"  # Major.Minor.Patch

log_buffer = logging.handlers.MemoryHandler(
    capacity=0,
    flushLevel=logging.CRITICAL,
    target=None,
)

logger.addHandler(log_buffer)
logger.setLevel(logging.DEBUG)


@dataclass
class ScriptSettings:
    """
    Script-specific settings loaded from config.
    """
    paths_to_scan: list[str] = field(default_factory=lambda: [
        "",
    ])
    ignore_these_exact_paths: list[str] = field(default_factory=list)
    any_part_of_path_to_ignore: list[str] = field(default_factory=lambda: [
        ".git",
        "RECYCLE",
        "System",
        "Recovery"
    ])


@dataclass
class LogSettings:
    mode: typing.Literal["per_run", "latest", "per_day", "single_file", "console_only"] = "per_run"
    folder: Path = Path("Logs")
    console_level: int = logging.DEBUG
    file_level: int = logging.DEBUG
    date_format: str = "%Y-%m-%dT%H:%M:%S"
    message_format: str = "%(asctime)s.%(msecs)03d [%(levelname)-8s] %(message)s"
    # message_format: str = "%(asctime)s.%(msecs)03d [%(levelname)-8s] %(module)s:%(funcName)s - %(message)s"
    max_files: int | None = 30
    open_log_after_run: bool = False


@dataclass
class RuntimeSettings:
    pause_on_error: bool = True
    always_pause: bool = False


@dataclass
class Config:
    script_settings: ScriptSettings = field(default_factory=ScriptSettings)
    log_settings: LogSettings = field(default_factory=LogSettings)
    runtime_settings: RuntimeSettings = field(default_factory=RuntimeSettings)


def path_is_ignored(path: str, ignore_these_exact_paths: list[str], any_part_of_path_to_ignore: list[str]) -> bool:
    """
    Determine if a path should be ignored based on exact matches or substrings.

    Args:
        path: The path to check.
        ignore_these_exact_paths: List of paths to ignore exactly.
        any_part_of_path_to_ignore: List of substrings; if any are in the path, it is ignored.

    Returns:
        True if the path should be ignored, False otherwise.
    """
    if path.lower() in (ignore.lower() for ignore in ignore_these_exact_paths):
        logger.debug("Path is explicitly ignored: %s", path)
        return True
    for part in any_part_of_path_to_ignore:
        if part.lower() in path.lower():
            logger.debug("Path contains ignored part '%s': %s", part, path)
            return True
    logger.debug("Path is not ignored: %s", path)
    return False


def dir_is_empty(path: str) -> bool:
    """
    Check if a directory is empty (no files in it or its subdirectories).

    Args:
        path: Directory path to check.

    Returns:
        True if the directory is empty, False otherwise.
    """
    if not os.path.isdir(path):
        logger.debug("Path is not a directory: %s", path)
        return False
    for _, _, files in os.walk(path):
        if files:
            logger.debug("Directory is not empty: %s", path)
            return False
    logger.debug("Directory is empty: %s", path)
    return True


def main(config: Config):
    """
    Main entry point for deleting empty folders based on config.

    Args:
        config: The configuration object containing script, log, and runtime settings.
    """
    script_settings = config.script_settings
    paths_to_scan = [os.path.abspath(os.path.join(os.getcwd(), path)) for path in script_settings.paths_to_scan]
    logger.debug("paths_to_scan = %s", paths_to_scan)
    ignore_these_exact_paths = list(script_settings.ignore_these_exact_paths)
    logger.debug("ignore_these_exact_paths = %s", ignore_these_exact_paths)
    any_part_of_path_to_ignore = list(script_settings.any_part_of_path_to_ignore)
    logger.debug("any_part_of_path_to_ignore = %s", any_part_of_path_to_ignore)

    deleted_dirs_count = 0
    deleted_dirs_list = []
    for path_to_scan in paths_to_scan:
        logger.info("Deleting empty dirs in '%s'...", path_to_scan)

        for root, dirs, _ in os.walk(path_to_scan, topdown=False):
            for dir_name in dirs:
                dir_path = os.path.join(root, dir_name)
                logger.debug("Scanning '%s'", dir_path)
                if path_is_ignored(dir_path, ignore_these_exact_paths, any_part_of_path_to_ignore):
                    continue
                if not dir_is_empty(dir_path):
                    continue
                try:
                    send2trash(dir_path)
                    deleted_dirs_count += 1
                    deleted_dirs_list.append(dir_path)
                    logger.info("Deleted %s", dir_path)
                except Exception as e:
                    logger.error("Failed to delete '%s': %s", dir_path, e)
                    logger.error("%s", traceback.format_exc())

    logger.debug("Deleted %d dir(s).", deleted_dirs_count)
    logger.debug("Deleted dirs:")
    for deleted_dir in deleted_dirs_list:
        logger.debug(" - %s", deleted_dir)


def enforce_max_log_count(dir_path: Path, max_count: int, script_name: str) -> None:
    """
    Enforce a maximum number of log files for this script.

    Rules:
    - Only affects files ending with `.log`
    - Only affects logs that contain the script name
    - Sorting is performed lexicographically by filename
    """
    if max_count <= 0:
        return

    if not dir_path.exists():
        return

    log_files = [f for f in dir_path.glob("*.log") if script_name in f.name]
    if len(log_files) <= max_count:
        return
    log_files.sort(key=lambda p: p.name)
    to_delete = log_files[:-max_count]
    for file in to_delete:
        try:
            file.unlink()
            logger.debug("Removed old log %s", file)
        except OSError as e:
            logger.debug("Failed removing old log %s: %s", file, e)


def build_log_path(log_settings: LogSettings) -> Path | None:
    """
    Builds the final log file path based on logging mode.
    """
    if log_settings.mode == "console_only":
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    day_stamp = datetime.now().strftime("%Y%m%d")

    script_name = Path(__file__).stem
    pc_name = socket.gethostname()

    log_dir = Path(log_settings.folder).expanduser().resolve()

    match log_settings.mode:
        case "per_run":
            filename = f"{timestamp}__{script_name}__{pc_name}.log"
        case "latest":
            filename = f"latest_{script_name}__{pc_name}.log"
        case "per_day":
            filename = f"{day_stamp}__{script_name}__{pc_name}.log"
        case "single_file":
            filename = f"{script_name}__{pc_name}.log"
        case _:
            filename = f"{timestamp}__{script_name}__{pc_name}.log"

    return log_dir / filename


class JsonArgsFilter(logging.Filter):
    """
    Automatically formats log arguments using JSON serialization rules.
    Guarantees double quotes around strings and paths without manual formatting.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            raw_args = list(record.args) if isinstance(record.args, tuple) else [record.args]
            processed_args = []
            for val in raw_args:
                if isinstance(val, Path):
                    processed_args.append(json.dumps(val.as_posix()))
                elif isinstance(val, str):
                    processed_args.append(json.dumps(val))
                else:
                    processed_args.append(val)
            record.args = tuple(processed_args)
        return True


def setup_logging(logger_obj: logging.Logger, log_settings: LogSettings) -> Path | None:
    """
    Set up console and file logging.
    """
    logger_obj.handlers.clear()
    logger_obj.setLevel(logging.DEBUG)
    logger_obj.propagate = False

    # Attach the automatic JSON formatting filter
    logger_obj.addFilter(JsonArgsFilter())

    log_path = build_log_path(log_settings)

    formatter = logging.Formatter(
        log_settings.message_format,
        datefmt=log_settings.date_format,
    )

    if log_path:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)

        except OSError as e:
            raise RuntimeError(f"Failed creating log directory {log_path.parent}") from e

        file_handler: logging.Handler

        match log_settings.mode:
            case "per_day":
                file_handler = TimedRotatingFileHandler(filename=log_path, when="midnight", interval=1, backupCount=log_settings.max_files or 0, encoding="utf-8")
            case "single_file":
                file_handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
            case _:
                file_handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")

        file_handler.setLevel(log_settings.file_level)
        file_handler.setFormatter(formatter)
        logger_obj.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_settings.console_level)
    console_handler.setFormatter(formatter)

    logger_obj.addHandler(console_handler)

    write_banner(logger_obj)

    if log_buffer:
        class _ForwardToLogger(logging.Handler):
            def emit(self, record):
                logger_obj.handle(record)

        forward_handler = _ForwardToLogger()
        log_buffer.setTarget(forward_handler)
        log_buffer.flush()
        log_buffer.close()

    if (log_settings.max_files and log_path and log_settings.mode not in ("per_day", "console_only")):
        enforce_max_log_count(dir_path=log_path.parent, max_count=log_settings.max_files, script_name=Path(__file__).stem)

    return log_path


def write_banner(logger_obj: logging.Logger):
    """
    Writes a clean session banner without log prefixes.
    """
    separator = "-" * 80

    banner = (
        f"{separator}\n"
        f"SCRIPT     | {json.dumps(Path(__file__).resolve().as_posix())}\n"
        f"VERSION    | {__version__}\n"
        f"START TIME | {datetime.now().isoformat(timespec='milliseconds')}\n"
        f"USER       | {os.getlogin()}\n"
        f"HOST       | {socket.gethostname()}\n"
        f"RUNTIME    | Python {sys.version.split()[0]}\n"
        f"{separator}"
    )

    original_formatters = {}

    class RawFormatter(logging.Formatter):
        """
        Formatter that outputs only the log message with no prefixes.
        """

        def format(self, record):
            return record.getMessage()

    try:
        for handler in logger_obj.handlers:
            original_formatters[handler] = handler.formatter
            handler.setFormatter(RawFormatter())

        logger_obj.info(banner)

    finally:
        for handler, formatter in original_formatters.items():
            handler.setFormatter(formatter)


def bootstrap():
    exit_code = 0
    log_path: Path | None = None
    config = Config()

    try:
        log_path = setup_logging(logger_obj=logger, log_settings=config.log_settings)
        main(config)

    except KeyboardInterrupt:
        logger.warning("Operation interrupted by user.")
        exit_code = 130

    except Exception as e:
        logger.exception("A fatal error has occurred: %s", e)
        exit_code = 1

    if (config.log_settings.open_log_after_run and log_path and log_path.exists()):
        try:
            match sys.platform:
                case plat if plat.startswith("win"):
                    os.startfile(log_path)
                case "darwin":
                    os.system(f'open "{log_path}"')
                case _:
                    os.system(f'xdg-open "{log_path}"')

        except Exception as e:
            logger.warning("Failed to open log file: %s", e)

    if (config.runtime_settings.always_pause or (config.runtime_settings.pause_on_error and exit_code != 0)):
        input("Press Enter to exit...")

    return exit_code


if __name__ == "__main__":
    sys.exit(bootstrap())

# logger = logging.getLogger(__name__)

# """
# Delete Empty Folders

# Deletes empty folders in the specified directory tree.
# """

# __version__ = "1.1.3"  # Major.Minor.Patch


# def read_toml(file_path: typing.Union[str, pathlib.Path]) -> dict:
#     """
#     Read configuration settings from the TOML file.
#     """
#     file_path = pathlib.Path(file_path)
#     if not file_path.exists():
#         raise FileNotFoundError(f'File not found: "{file_path}"')
#     config = toml.load(file_path)
#     return config


# def main():
#     """Old code was here"""

# def format_duration_long(duration_seconds: float) -> str:
#     """
#     Format duration in a human-friendly way, showing only the two largest non-zero units.
#     For durations >= 1s, do not show microseconds or nanoseconds.
#     For durations >= 1m, do not show milliseconds.
#     """
#     ns = int(duration_seconds * 1_000_000_000)
#     units = [
#         ('y', 365 * 24 * 60 * 60 * 1_000_000_000),
#         ('mo', 30 * 24 * 60 * 60 * 1_000_000_000),
#         ('d', 24 * 60 * 60 * 1_000_000_000),
#         ('h', 60 * 60 * 1_000_000_000),
#         ('m', 60 * 1_000_000_000),
#         ('s', 1_000_000_000),
#         ('ms', 1_000_000),
#         ('us', 1_000),
#         ('ns', 1),
#     ]
#     parts = []
#     for name, factor in units:
#         value, ns = divmod(ns, factor)
#         if value:
#             parts.append(f'{value}{name}')
#         if len(parts) == 2:
#             break
#     if not parts:
#         return "0s"
#     return "".join(parts)

# def enforce_max_folder_size(log_dir: pathlib.Path, max_bytes: int) -> None:
#     """
#     Enforce a maximum total size for all logs in the folder.
#     Deletes oldest logs until below limit.
#     """
#     if max_bytes is None:
#         return

#     files = sorted(
#         [f for f in log_dir.glob("*.log*") if f.is_file()],
#         key=lambda f: f.stat().st_mtime
#     )

#     total_size = sum(f.stat().st_size for f in files)

#     while total_size > max_bytes and files:
#         oldest = files.pop(0)
#         try:
#             size = oldest.stat().st_size
#             oldest.unlink()
#             logger.debug(f'Deleted "{oldest}"')
#             total_size -= size
#         except Exception:
#             logger.error(f'Failed to delete "{oldest}"', exc_info=True)
#             continue

# def setup_logging(
#         logger: logging.Logger,
#         log_file_path: typing.Union[str, pathlib.Path],
#         max_folder_size_bytes: typing.Union[int, None] = None,
#         console_logging_level: int = logging.DEBUG,
#         file_logging_level: int = logging.DEBUG,
#         log_message_format: str = "%(asctime)s.%(msecs)03d %(levelname)s [%(funcName)s]: %(message)s",
#         date_format: str = "%Y-%m-%d %H:%M:%S"
# ) -> None:

#     log_file_path = pathlib.Path(log_file_path)
#     log_dir = log_file_path.parent
#     log_dir.mkdir(parents=True, exist_ok=True)

#     logger.handlers.clear()
#     logger.setLevel(file_logging_level)

#     formatter = logging.Formatter(log_message_format, datefmt=date_format)

#     # File Handler
#     file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
#     file_handler.setLevel(file_logging_level)
#     file_handler.setFormatter(formatter)
#     logger.addHandler(file_handler)

#     # Console Handler
#     console_handler = logging.StreamHandler(sys.stdout)
#     console_handler.setLevel(console_logging_level)
#     console_handler.setFormatter(formatter)
#     logger.addHandler(console_handler)

#     if max_folder_size_bytes is not None:
#         enforce_max_folder_size(log_dir, max_folder_size_bytes)

# def load_config(file_path: typing.Union[str, pathlib.Path]) -> dict:
#     file_path = pathlib.Path(file_path)
#     if not file_path.exists():
#         raise FileNotFoundError(f'File not found: "{file_path}"')
#     config = read_toml(file_path)
#     return config

# if __name__ == "__main__":
#     error = 0
#     try:
#         script_name = pathlib.Path(__file__).stem
#         config_path = pathlib.Path(f'{script_name}_config.toml')
#         # config_path = pathlib.Path("config.toml")
#         config = load_config(config_path)

#         logging_config = config.get("logging", {})
#         console_logging_level = getattr(logging, logging_config.get("console_logging_level", "INFO").upper(), logging.DEBUG)
#         file_logging_level = getattr(logging, logging_config.get("file_logging_level", "INFO").upper(), logging.DEBUG)
#         log_message_format = logging_config.get("log_message_format", "%(asctime)s.%(msecs)03d %(levelname)s [%(funcName)s]: %(message)s")
#         logs_folder_name = logging_config.get("logs_folder_name", "logs")
#         max_folder_size_bytes = logging_config.get("max_folder_size", None)

#         pc_name = socket.gethostname()
#         timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
#         log_dir = pathlib.Path(logs_folder_name) / script_name
#         log_dir.mkdir(parents=True, exist_ok=True)
#         log_file_name = f'{timestamp}_{script_name}_{pc_name}.log'
#         log_file_path = log_dir / log_file_name

#         setup_logging(
#             logger,
#             log_file_path,
#             max_folder_size_bytes=max_folder_size_bytes,
#             console_logging_level=console_logging_level,
#             file_logging_level=file_logging_level,
#             log_message_format=log_message_format
#         )
#         start_time = time.perf_counter_ns()
#         logger.info(f'Script: "{script_name}" | Version: {__version__} | Host: "{pc_name}"')
#         main()
#         end_time = time.perf_counter_ns()
#         duration = end_time - start_time
#         duration = format_duration_long(duration / 1e9)
#         logger.info(f'Execution completed in {duration}.')
#     except KeyboardInterrupt:
#         logger.warning("Operation interrupted by user.")
#         error = 130
#     except Exception as e:
#         logger.warning(f'A fatal error has occurred: {repr(e)}\n{traceback.format_exc()}')
#         error = 1
#     finally:
#         for handler in logger.handlers:
#             handler.close()
#         logger.handlers.clear()
#         input("Press Enter to exit...")
#         sys.exit(error)
