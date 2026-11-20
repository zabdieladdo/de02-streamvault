"""Errors that stop the pipeline run."""


class PipelineStopError(Exception):
    """Raised when continuing would produce wrong output, so the run must halt."""
