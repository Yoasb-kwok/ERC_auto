"""One UDP sender for the block UI and the student SDK.

The datagram is still ``L:,R:,B:,S:`` to ``192.168.4.1:4210``. Log-only mode
prints that line and does not open the network.
"""

from __future__ import annotations

import os
import socket
import threading

from ai.wire import format_car_command

UDP_IP = "192.168.4.1"
UDP_PORT = 4210

FORWARD_SPEED = 100
BACKWARD_SPEED = 100
TURN_SPEED_FACTOR = 0.5
MAX_SPEED = 190

SERVO_STRAIGHT = 90
SERVO_LEFT_MAX = 50
SERVO_RIGHT_MAX = 130

STOP_SIGNAL = 1

_lock = threading.Lock()
_sock = None


def log_only_from_env() -> bool:
    return os.environ.get("ERC_LOG_ONLY", "").strip().lower() in {"1", "true", "yes", "on"}


def ensure_socket():
    """Create the UDP socket if needed. Raises ``socket.error`` on failure."""
    global _sock
    with _lock:
        if _sock is None:
            _sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            _sock.settimeout(0.1)
        return _sock


def close_socket() -> None:
    global _sock
    with _lock:
        if _sock is not None:
            _sock.close()
            _sock = None


def transmit_datagram(command_str, dry_run=None, debug=False):
    """Send one already-formatted ``L:,R:,B:,S:`` datagram.

    ``send_car_command`` formats and then calls this. The demo1 soft gateway
    rewrites the line first, then uses the same socket (or the same log-only
    print). ``dry_run`` None follows ``ERC_LOG_ONLY``. True skips the socket.
    Returns the string including the trailing newline.
    """
    global _sock
    if not str(command_str).endswith("\n"):
        command_str = f"{command_str}\n"
    use_dry_run = log_only_from_env() if dry_run is None else bool(dry_run)
    with _lock:
        if use_dry_run:
            print(f"[log-only] {command_str.strip()}")
            return command_str
        try:
            if _sock is None:
                _sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                _sock.settimeout(0.1)
            _sock.sendto(command_str.encode(), (UDP_IP, UDP_PORT))
            if debug:
                print(f"Sent: {command_str.strip()}")
        except Exception as exc:
            print(f"UDP Send Error: {exc}")
    return command_str


def send_car_command(speed, steering_angle, stop_override=0, dry_run=None, debug=False):
    """Format and send one car datagram. Returns the string including newline.

    ``dry_run`` None follows ``ERC_LOG_ONLY``. True skips the socket.
    """
    command_str = format_car_command(
        speed,
        steering_angle,
        stop_override,
        max_speed=MAX_SPEED,
        servo_min=SERVO_LEFT_MAX,
        servo_max=SERVO_RIGHT_MAX,
        stop_signal=STOP_SIGNAL,
    )
    return transmit_datagram(command_str, dry_run=dry_run, debug=debug)
