"""Recover server-recorded input provenance without trusting operation parameters."""
from pathlib import Path

from cytools_core import CyToolError


def original_path(context):
    """The Core stages inputs before invoking the operation handler.

    Preserve that name and sibling-reference location when creating a persistent
    project. Analysis still consumes the private snapshot, never the live source.
    """
    # The persisted job contains the validated request BEFORE automatic staging.
    # A separate user-supplied sourcePath parameter would allow forged provenance.
    with context.runtime._cv:
        job = context.runtime._jobs[context.job_id]
        if job['operationId'] != 'open_file':
            raise CyToolError('InvalidState', 'Input provenance requires an open_file job.')
        source = Path(job['parameters']['path']).expanduser()
        root = context.runtime.input_root
    if not source.is_absolute():
        source = (root / source).resolve()
        if not source.is_relative_to(root):
            raise CyToolError('AccessDenied', 'Relative input escapes the input directory.')
    return str(source.resolve())
