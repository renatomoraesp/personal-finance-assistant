class OpenRouterError(Exception):
    pass


class OpenRouterResponseError(OpenRouterError):
    pass


class EmptyCompletionError(OpenRouterError):
    pass
