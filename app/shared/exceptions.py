class GatewayError(Exception):
    pass


class UpstreamAuthError(GatewayError):
    pass


class UpstreamProviderError(GatewayError):
    pass
