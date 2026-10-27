"""
KPI Intelligence — Ingestion Paths & Filesystem Resilience.

Provides cross-platform, long-path resilient filesystem utilities:
- Configurable short staging root resolution (defaulting to C:\\kpi_tmp on Windows, local_data/temp_ingestion on Unix)
- Environment variable overrides: KPI_TEMP_DIR / KPI_INGESTION_TEMP_DIR
- Windows extended-length path prefixing (\\\\?\\) to bypass the MAX_PATH (260-char) limit
- Path component length validation (max 255 chars per filename/dirname)
- Safe directory creation, file opening, and directory tree deletion
- Diagnostic path sanitization (redacting user home folders for privacy)
- Collision-resistant, compact job directory names (j_<12-hex-chars>)
"""

import os
import sys
import re
import uuid
import tempfile
import stat
import shutil
import logging
from pathlib import Path
from typing import Tuple, Optional, Union, Dict, Any

logger = logging.getLogger("kpi_intel.ingestion.paths")

WINDOWS_MAX_PATH = 260
MAX_PATH_COMPONENT_LENGTH = 255


def is_windows() -> bool:
    """Returns True if the current operating system is Windows."""
    return sys.platform == "win32" or os.name == "nt"


def to_extended_path(path: Union[str, Path]) -> str:
    """
    Converts an absolute path to Windows extended-length syntax (\\\\?\\) on Windows.
    Bypasses the traditional Win32 260-character MAX_PATH limit.
    On non-Windows systems, returns the normalized absolute path unchanged.
    """
    str_path = str(path)
    if not is_windows():
        return os.path.abspath(str_path)

    # Normalize backslashes for Windows NT syntax
    norm_path = str_path.replace("/", "\\")

    # Already prefixed with extended syntax
    if norm_path.startswith("\\\\?\\"):
        return norm_path

    # Windows UNC network share path: \\server\share\... -> \\?\UNC\server\share\...
    if norm_path.startswith("\\\\"):
        return f"\\\\?\\UNC\\{norm_path[2:]}"

    # Local drive path: C:\path\... -> \\?\C:\path\...
    if re.match(r"^[a-zA-Z]:[\\/]", norm_path):
        return f"\\\\?\\{norm_path[:2].upper()}{norm_path[2:]}"

    abs_path = os.path.abspath(str_path).replace("/", "\\")
    if abs_path.startswith("\\\\"):
        return f"\\\\?\\UNC\\{abs_path[2:]}"
    return f"\\\\?\\{abs_path}"


def strip_extended_prefix(path: str) -> str:
    """Removes \\\\?\\ or \\\\?\\UNC\\ prefix for human-readable display."""
    if path.startswith("\\\\?\\UNC\\"):
        return f"\\\\{path[8:]}"
    if path.startswith("\\\\?\\"):
        return path[4:]
    return path


def sanitize_path_for_diagnostics(path: str) -> str:
    """
    Sanitizes file paths for logs and diagnostic messages by:
    1. Stripping extended-length prefixes.
    2. Redacting sensitive user home directories to protect privacy and credentials.
    """
    clean = strip_extended_prefix(str(path))
    # Redact Windows user home: C:\Users\<username>\...
    clean = re.sub(r"(?i)([a-z]:\\users\\)[^\\]+", r"\1[REDACTED_USER]", clean)
    # Redact macOS user home: /Users/<username>/...
    clean = re.sub(r"^/Users/[^/]+", "/Users/[REDACTED_USER]", clean)
    # Redact Linux user home: /home/<username>/...
    clean = re.sub(r"^/home/[^/]+", "/home/[REDACTED_USER]", clean)
    return clean


def validate_path_component_lengths(rel_path: str, max_len: int = MAX_PATH_COMPONENT_LENGTH) -> None:
    """
    Validates that no individual path component (directory or file name) exceeds
    the filesystem's maximum allowed component length (255 characters on NTFS/ext4/APFS).
    """
    normalized = rel_path.replace("\\", "/").strip().lstrip("/")
    parts = [p for p in normalized.split("/") if p]
    for part in parts:
        if len(part) > max_len:
            raise ValueError(
                f"Path component '{part[:35]}...' exceeds maximum component length "
                f"of {max_len} characters (actual length: {len(part)} chars)."
            )


def generate_short_job_id() -> Tuple[str, str]:
    """
    Generates a full UUID job identifier for API and tracking consistency,
    along with a compact directory name to minimize temporary workspace depth.

    Returns:
        (job_id, job_dirname)
        e.g. ("job_12345678-1234-5678-1234-567812345678", "j_a1b2c3d4e5f6")
    """
    full_uuid = uuid.uuid4()
    job_id = f"job_{full_uuid}"
    job_dirname = f"j_{full_uuid.hex[:12]}"
    return job_id, job_dirname


def resolve_staging_root(custom_path: Optional[str] = None) -> str:
    """
    Resolves, validates, and initializes the root temporary workspace for ingestion.

    Resolution Precedence:
    1. Explicit custom_path argument (if provided).
    2. KPI_TEMP_DIR or KPI_INGESTION_TEMP_DIR environment variable.
    3. Platform-specific default:
       - On Windows: C:\\kpi_tmp (if C: drive exists and is writable);
         fallback to %TEMP%\\kpi_tmp if C:\\ is restricted.
       - On Unix/macOS: local_data/temp_ingestion relative to repo root;
         fallback to /tmp/kpi_tmp if not writable.

    Raises:
        PermissionError: If directory cannot be created or has no write permissions.
    """
    configured = (
        custom_path
        or os.environ.get("KPI_TEMP_DIR")
        or os.environ.get("KPI_INGESTION_TEMP_DIR")
    )

    if configured:
        target = os.path.abspath(configured.strip())
        _ensure_writable_directory(target, is_explicit=True)
        return target

    # Default platform resolution
    if is_windows():
        primary_win_path = "C:\\kpi_tmp"
        try:
            _ensure_writable_directory(primary_win_path, is_explicit=False)
            return primary_win_path
        except Exception as ex:
            logger.warning(
                "Could not create default Windows temp directory '%s': %s. Falling back to system temp.",
                primary_win_path,
                ex,
            )
            fallback_win = os.path.join(tempfile.gettempdir(), "kpi_tmp")
            _ensure_writable_directory(fallback_win, is_explicit=False)
            return fallback_win
    else:
        # macOS / Linux default
        workspace_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        local_target = os.path.join(workspace_root, "local_data", "temp_ingestion")
        try:
            _ensure_writable_directory(local_target, is_explicit=False)
            return local_target
        except Exception:
            fallback_unix = os.path.join(tempfile.gettempdir(), "kpi_tmp")
            _ensure_writable_directory(fallback_unix, is_explicit=False)
            return fallback_unix


def _ensure_writable_directory(directory_path: str, is_explicit: bool = False) -> None:
    """
    Validates that the target directory exists (or can be created) and is writable.
    Throws descriptive errors if unavailable.
    """
    ext_path = to_extended_path(directory_path)
    try:
        os.makedirs(ext_path, exist_ok=True)
    except Exception as ex:
        safe_path = sanitize_path_for_diagnostics(directory_path)
        err_msg = (
            f"Configured temporary ingestion directory '{safe_path}' cannot be created: {ex}. "
            "Please check permissions or specify an accessible folder via KPI_TEMP_DIR."
        ) if is_explicit else f"Temporary directory '{safe_path}' cannot be created: {ex}."
        raise PermissionError(err_msg) from ex

    # Probe writability
    probe_name = f".kpi_probe_{uuid.uuid4().hex[:8]}.tmp"
    probe_path = os.path.join(ext_path, probe_name)
    try:
        with open(probe_path, "w", encoding="utf-8") as f:
            f.write("probe")
        if os.path.exists(probe_path):
            os.remove(probe_path)
    except Exception as ex:
        safe_path = sanitize_path_for_diagnostics(directory_path)
        err_msg = (
            f"Configured temporary ingestion directory '{safe_path}' is not writable: {ex}. "
            "Please grant write permissions or specify an accessible folder via KPI_TEMP_DIR."
        ) if is_explicit else f"Temporary directory '{safe_path}' is not writable: {ex}."
        raise PermissionError(err_msg) from ex


def safe_makedirs(path: Union[str, Path], exist_ok: bool = True) -> None:
    """Creates directory with Windows long-path prefixing and diagnostic error reporting."""
    ext_path = to_extended_path(path)
    try:
        os.makedirs(ext_path, exist_ok=exist_ok)
    except OSError as ex:
        safe_p = sanitize_path_for_diagnostics(str(path))
        path_len = len(str(path))
        win_err = getattr(ex, "winerror", None)
        err_no = getattr(ex, "errno", None)
        if win_err == 206 or err_no == 36 or "too long" in str(ex).lower():
            raise OSError(
                f"[WinError 206] Directory path length limit exceeded ({path_len} chars >= {WINDOWS_MAX_PATH}): "
                f"'{safe_p}'. Operation: makedirs. Configure a short workspace via KPI_TEMP_DIR."
            ) from ex
        raise


def safe_open(path: Union[str, Path], mode: str = "r", **kwargs):
    """Opens a file with Windows long-path prefixing and diagnostic error reporting."""
    ext_path = to_extended_path(path)
    try:
        return open(ext_path, mode, **kwargs)
    except OSError as ex:
        safe_p = sanitize_path_for_diagnostics(str(path))
        path_len = len(str(path))
        win_err = getattr(ex, "winerror", None)
        err_no = getattr(ex, "errno", None)
        if win_err == 206 or err_no == 36 or "too long" in str(ex).lower():
            raise OSError(
                f"[WinError 206] File path length limit exceeded ({path_len} chars >= {WINDOWS_MAX_PATH}): "
                f"'{safe_p}'. Operation: open('{mode}'). Configure a short workspace via KPI_TEMP_DIR."
            ) from ex
        raise


def safe_rmtree(path: Union[str, Path], ignore_errors: bool = True) -> None:
    """Removes a directory tree cleanly, handling Windows read-only files and long paths."""
    ext_path = to_extended_path(path)
    if not os.path.exists(ext_path):
        return

    def _remove_readonly(func, fpath, exc_info):
        # Clear read-only attribute and re-attempt
        try:
            os.chmod(fpath, stat.S_IWRITE)
            func(fpath)
        except Exception:
            pass

    try:
        shutil.rmtree(ext_path, ignore_errors=False, onerror=_remove_readonly)
    except Exception:
        if not ignore_errors:
            raise


def format_path_error_diagnostic(path: str, operation: str, error: Exception) -> Dict[str, Any]:
    """Formats a structured, non-secret diagnostic dict for filesystem errors."""
    path_len = len(str(path))
    safe_path = sanitize_path_for_diagnostics(path)
    win_err = getattr(error, "winerror", None)
    is_path_too_long = (
        win_err == 206
        or getattr(error, "errno", None) == 36
        or "too long" in str(error).lower()
        or path_len >= WINDOWS_MAX_PATH
    )

    return {
        "code": "PATH_LENGTH_EXCEEDED" if is_path_too_long else "FILESYSTEM_OPERATION_FAILED",
        "operation": operation,
        "path_length": path_len,
        "sanitized_path": safe_path,
        "max_limit": WINDOWS_MAX_PATH,
        "error": str(error),
        "is_path_too_long": is_path_too_long,
        "remediation": "Configure a shorter temporary root via KPI_TEMP_DIR (e.g. C:\\kpi_tmp) to avoid deep nesting."
        if is_path_too_long
        else "Check directory permissions and available disk space.",
    }
