"""Command syntax errors; domain exceptions remain in model."""


class CommandError(Exception):
    """Invalid command syntax with a corrective, unprefixed reason."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
