"""
Terminal-based Hotkey Input Handler for VAD Data Collector

Provides non-blocking keyboard input capture for metadata tagging.
"""

import sys
import tty
import termios
import select
import logging
from typing import Optional


class HotkeyHandler:
    """
    Non-blocking terminal keyboard input handler.

    Captures single keypress events without requiring Enter key.
    Works in terminal environments including SSH sessions.
    """

    def __init__(self):
        """Initialize hotkey handler with terminal settings."""
        self.logger = logging.getLogger(__name__)
        self.fd = sys.stdin.fileno()
        self.old_settings = None

    def __enter__(self):
        """Enter context manager - configure terminal for raw input."""
        try:
            self.old_settings = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)
            self.logger.debug("Terminal configured for raw input")
        except Exception as e:
            self.logger.error(f"Failed to configure terminal: {e}")
            raise
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context manager - restore terminal settings."""
        if self.old_settings:
            try:
                termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old_settings)
                self.logger.debug("Terminal settings restored")
            except Exception as e:
                self.logger.error(f"Failed to restore terminal: {e}")

    def get_key(self, timeout: float = 0.0) -> Optional[str]:
        """
        Get a single keypress if available.

        Args:
            timeout: Maximum time to wait for input in seconds (0 = non-blocking)

        Returns:
            Single character key, or None if no input available
        """
        # Check if input is available using select
        ready, _, _ = select.select([sys.stdin], [], [], timeout)

        if ready:
            try:
                key = sys.stdin.read(1)
                return key
            except Exception as e:
                self.logger.error(f"Error reading key: {e}")
                return None
        return None


def print_hotkey_help():
    """Print hotkey reference guide to terminal."""
    help_text = """
╔══════════════════════════════════════════════════════════════╗
║             VAD Data Collector - Hotkey Reference            ║
╠══════════════════════════════════════════════════════════════╣
║  TIMED TAGS (30 seconds)                                     ║
║  [1] One speaker close to mic                                ║
║  [2] Two speakers speaking, variable distance                ║
║  [0] Music playing                                           ║
║  [9] Video playing                                           ║
║  [8] Loud ambient noise                                      ║
║                                                              ║
║  PERSISTENT TAGS (toggle on/off)                             ║
║  [q] One speaker close to mic (persistent)                   ║
║  [w] Two speakers speaking (persistent)                      ║
║  [p] Music playing (persistent)                              ║
║  [o] Video playing (persistent)                              ║
║  [i] Loud ambient noise (persistent)                         ║
║                                                              ║
║  CONTROL                                                     ║
║  [h] Show this help                                          ║
║  [Ctrl+C] Stop collector                                     ║
╚══════════════════════════════════════════════════════════════╝
"""
    print(help_text)
