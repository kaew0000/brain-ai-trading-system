"""
utils/systemd_notify.py — Minimal sd_notify() client, no external deps.

Implements the systemd "notify" datagram protocol directly over the
NOTIFY_SOCKET unix socket, rather than depending on the `sdnotify` PyPI
package or linking libsystemd. The protocol is a handful of lines — see
https://www.freedesktop.org/software/systemd/man/sd_notify.html (protocol
section) — not worth a new dependency for.

    READY=1      — startup finished; pairs with systemd unit Type=notify
    WATCHDOG=1   — "I'm alive"; pets WatchdogSec= (systemd kills+restarts
                   the unit if this isn't received within WatchdogSec)
    STOPPING=1   — graceful shutdown in progress
    STATUS=text  — free-form status line, shown in `systemctl status`

Every function here is a safe no-op (returns False, logs at debug) when
NOTIFY_SOCKET isn't set in the environment — i.e. when not actually running
under systemd (dev machine, paper-mode testing, unit tests, CI). Safe to
call unconditionally from anywhere in the app.
"""
from __future__ import annotations
import os
import socket
from utils.logger import get_logger

logger = get_logger(__name__)


def notify(state: str) -> bool:
    """Send a raw sd_notify state string, e.g. 'READY=1'.

    Returns True if NOTIFY_SOCKET was set and the datagram was sent
    (systemd does not ack — this only confirms the local send succeeded),
    False if there was no socket to send to or the send failed. The
    return value is safe to ignore; this never raises.
    """
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return False
    # Abstract namespace sockets are prefixed with '@' in the env var and
    # need a leading NUL byte instead when handed to socket().
    if addr.startswith("@"):
        addr = "\0" + addr[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.sendto(state.encode("utf-8"), addr)
        return True
    except Exception as exc:
        logger.debug(f"sd_notify({state!r}) failed: {exc}")
        return False


def notify_ready() -> bool:
    return notify("READY=1")


def notify_watchdog() -> bool:
    return notify("WATCHDOG=1")


def notify_stopping() -> bool:
    return notify("STOPPING=1")


def notify_status(text: str) -> bool:
    return notify(f"STATUS={text}")
