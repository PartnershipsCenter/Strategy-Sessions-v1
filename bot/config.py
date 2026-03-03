"""Bot-specific config — wraps core config for backward compatibility."""

from core.config import Config, load_config

__all__ = ["Config", "load_config"]
