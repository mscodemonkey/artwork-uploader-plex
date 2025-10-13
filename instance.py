"""
Instance identifier for tracking CLI/web sessions.
"""

from typing import Optional, Literal


class Instance:
    """
    Represents a session instance for tracking operations in CLI or web mode.

    Attributes:
        id: Unique identifier for the instance (UUID for web, can be None for CLI)
        mode: Operating mode - either "cli" or "web"
        broadcast: Whether to broadcast updates to all connected clients
    """

    def __init__(
        self,
        id: Optional[str] = None,
        mode: Literal["cli", "web"] = "web",
        broadcast: bool = False
    ) -> None:
        self.id = id
        self.mode = mode
        self.broadcast = broadcast