class JDPathError(Exception):
    def __init__(self, path, message):
        self.path = path
        super().__init__(message)


class NotJohnnyDecimalDirectoryError(JDPathError):
    def __init__(self, path):
        super().__init__(path, f"The path {path} is not in a Johnny Decimal directory.")
