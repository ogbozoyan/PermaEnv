"""Content-free errors shared by local history operations."""


class HistoryError(Exception):
    def __init__(self, code: str, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}
