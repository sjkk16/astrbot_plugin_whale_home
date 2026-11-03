class HomeError(Exception):
    def __init__(self, message: str, status: int = 400, code: str = "invalid"):
        self.message = message
        self.status = status
        self.code = code
        super().__init__(message)
