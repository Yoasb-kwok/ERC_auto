"""ERC WiFi datagram. Same contract ``8266.ino`` parses. Do not invent fields.

``L`` is the reverse channel, ``R`` is the forward channel, ``B`` is the
brake (1 = stop override), ``S`` is the steering servo in degrees.
"""

from __future__ import annotations


def format_car_command(
    speed,
    steering_angle,
    stop_override=0,
    *,
    max_speed=190,
    servo_min=50,
    servo_max=130,
    stop_signal=1,
) -> str:
    """Format one ``L:,R:,B:,S:`` command, including the trailing newline.

    ``speed > 0`` drives forward on ``R``. ``speed < 0`` drives reverse on
    ``L``. Both channels at rest promote ``B`` to ``stop_signal`` when the
    caller did not already set a stop override. This matches
    ``send_car_command`` in ``AutoERC_PyQt5.py``.
    """
    left = 0
    right = 0
    if speed > 0:
        right = speed
    elif speed < 0:
        left = -speed

    brake = stop_override
    if stop_override == 0 and left == 0 and right == 0:
        brake = stop_signal

    left = int(max(0, min(max_speed, left)))
    right = int(max(0, min(max_speed, right)))
    servo = int(max(servo_min, min(servo_max, steering_angle)))
    brake = int(brake)
    return f"L:{left},R:{right},B:{brake},S:{servo}\n"
