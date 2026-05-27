import pygame
import socket
import time
import sys
import logitech_steering_wheel
import argparse

# ANSI color codes for terminal
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    RESET = '\033[0m'

CYCLE_TIME = 0.1 # Main loop frequency

# Parse command-line arguments for debug mode
parser = argparse.ArgumentParser(description="Steering wheel control script")
parser.add_argument('--debug', type=bool, default=False, 
                   help='Enable debug mode for extra logging')
args = parser.parse_args()
DEBUG_MODE = args.debug

# Initialize Pygame and joystick
pygame.init()
pygame.joystick.init()

if pygame.joystick.get_count() == 0:
    print("No joystick detected. Please connect your driving steering wheel.")
    sys.exit()
else:
    joystick = pygame.joystick.Joystick(0)
    joystick.init()
    print(f"Joystick detected: {joystick.get_name()}")

# Initialize force feedback and set 360-degree rotation
try:
    if logitech_steering_wheel.initialize():
        if logitech_steering_wheel.is_connected(0):
            print("Force feedback initialized")
            logitech_steering_wheel.set_operating_range(0, 360)
            print("Steering wheel rotation set to 360 degrees")
        else:
            print("G27 not connected for force feedback")
            logitech_steering_wheel = None
    else:
        print("Force feedback initialization failed")
        logitech_steering_wheel = None
except Exception as e:
    print(f"Force feedback error: {e}")
    logitech_steering_wheel = None

# UDP settings
UDP_IP = "192.168.4.1"  # ESP8266 AP IP
UDP_PORT = 4210
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# Force feedback settings
SPRING_FORCE_COEFFICIENT = 100
SPRING_FORCE_SATURATION = 100

# State variables
last_left_speed = 0
last_right_speed = 0
last_stop_state = 0
last_servo_angle = 90
accel_pressed = False  # Track if accelerator has been pressed
brake_pressed = False  # Track if brake has been pressed

try:
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                sys.exit()

        # Read G27 inputs
        wheel_axis = joystick.get_axis(0)  # Steering: -1 (left) to 1 (right)
        try:
            accel_axis = joystick.get_axis(1)  # Accelerator
            brake_axis = joystick.get_axis(2)  # Brake
        except pygame.error:
            print("Invalid axis. Check joystick configuration.")
            sys.exit()
        stop_button = joystick.get_button(0)  # Stop button

        # Update pressed flags
        if accel_axis != 0:
            accel_pressed = True
        if brake_axis != 0:
            brake_pressed = True

        # Debug: Print raw axis values and pressed flags
        if DEBUG_MODE:
            debug_msg = f"Raw inputs: wheel={wheel_axis:.3f}, accel={accel_axis:.3f}, brake={brake_axis:.3f}, "
            debug_msg += f"stop={stop_button}, accel_pressed={accel_pressed}, brake_pressed={brake_pressed}"
            print(f"{Colors.BLUE}{debug_msg}{Colors.RESET}")

        # Process accelerator and brake
        if stop_button:
            left_speed = 0
            right_speed = 0
            stop_state = 1
        else:
            # Process accelerator for forward speed
            accel_value = accel_axis if accel_pressed else 1.0  # Treat as released until pressed
            right_speed = int((1.0 - accel_value) * 127.5) if accel_value < 1.0 else 0  # Forward: 0 to 255
            # Process brake for backward speed
            brake_value = brake_axis if brake_pressed else 1.0  # Treat as released until pressed
            left_speed = int((1.0 - brake_value) * 127.5) if brake_value < 1.0 else 0  # Backward: 0 to 255
            stop_state = 0

        # Process steering
        servo_angle = int(90 * (1 + wheel_axis))  # -1 (left) → 0°, 1 (right) → 180°
        servo_angle = max(0, min(180, servo_angle))

        # Constrain speeds
        left_speed = max(0, min(255, left_speed))  # Backward
        right_speed = max(0, min(255, right_speed))  # Forward

        # Determine direction for display
        direction = "Left" if wheel_axis < 0 else \
                   "Right" if wheel_axis > 0 else "Straight"

        # Apply force feedback
        if logitech_steering_wheel and not stop_state:
            wheel_deviation = abs(wheel_axis) * 100
            logitech_steering_wheel.play_spring_force(0, 0, SPRING_FORCE_SATURATION, int(wheel_deviation))
            speed = max(left_speed, right_speed)
            if speed > 0:
                logitech_steering_wheel.play_constant_force(0, int(speed * 0.2))
        elif logitech_steering_wheel:
            logitech_steering_wheel.stop_spring_force(0)
            logitech_steering_wheel.stop_constant_force(0)

        # Print state
        state_msg = f"Steering: {Colors.YELLOW}{wheel_axis:.3f}{Colors.RESET}, "
        state_msg += f"Direction: {Colors.GREEN}{direction}{Colors.RESET}, "
        state_msg += f"LSpeed={Colors.RED}{left_speed}{Colors.RESET}, "
        state_msg += f"RSpeed={Colors.RED}{right_speed}{Colors.RESET}, "
        state_msg += f"Servo Angle={Colors.RED}{servo_angle}{Colors.RESET}, "
        state_msg += f"Accel={'Pressed' if accel_value < 1.0 else 'Released'}, "
        state_msg += f"Brake={'Pressed' if brake_value < 1.0 else 'Released'}, "
        state_msg += f"Stop={'Pressed' if stop_button else 'Released'}"
        print(state_msg)

        # Send command if state changes
        if (left_speed != last_left_speed or
            right_speed != last_right_speed or
            stop_state != last_stop_state or
            servo_angle != last_servo_angle):
            command = f"L:{left_speed},R:{right_speed},B:{stop_state},S:{servo_angle}\n"
            sock.sendto(command.encode(), (UDP_IP, UDP_PORT))
            if DEBUG_MODE: 
                print(f"{Colors.HEADER}Sent: {command.strip()}{Colors.RESET}")   
            time.sleep(0.01)  # Small delay to ensure ESP8266 processes packet

        # Update states
        last_left_speed = left_speed
        last_right_speed = right_speed
        last_stop_state = stop_state
        last_servo_angle = servo_angle

        time.sleep(CYCLE_TIME)

except KeyboardInterrupt:
    print("Program terminated")
finally:
    if logitech_steering_wheel:
        logitech_steering_wheel.stop_spring_force(0)
        logitech_steering_wheel.stop_constant_force(0)
        logitech_steering_wheel.shutdown()
    sock.close()
    pygame.quit()
