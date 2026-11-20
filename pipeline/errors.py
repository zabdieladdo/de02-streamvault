"""Errors that stop the pipeline run."""


class PipelineStopError(Exception):
    """Raised when continuing would produce wrong output, so the run must halt.

    `check_id` names the failed check when a check caused the stop (for the run status file).
    """

    def __init__(self, message: str = "", check_id: str | None = None):
        """Keep the message and, when a check caused the stop, the id of that check."""
        super().__init__(message)
        self.check_id = check_id
