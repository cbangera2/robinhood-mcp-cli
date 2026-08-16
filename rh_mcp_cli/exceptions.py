"""Domain errors for the CLI."""


class RhError(Exception):
    """Base error."""


class AuthError(RhError):
    """Authentication or token-state problem."""


class MCPError(RhError):
    """An MCP tool call was rejected or failed."""


class UsageError(RhError):
    """Bad or incomplete command-line invocation."""


class Cancelled(RhError):
    """A mutating command was declined by the operator."""