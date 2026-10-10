import os
import socket
import sys
import threading
import time
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLabel, QTextEdit, QScrollArea, QFrame, QLineEdit,
                             QMessageBox, QGraphicsView, QGraphicsScene, QGraphicsItem, QGraphicsRectItem,
                             QSplitter, QCheckBox, QComboBox)
from PyQt5.QtCore import Qt, QPoint, QRect, QTimer, pyqtSignal, QObject, QMimeData
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QFont, QPainterPath, QDrag

from ai.command_gateway import CommandGateway, stall_timeout_from_env
from ai.transport import (
    BACKWARD_SPEED,
    FORWARD_SPEED,
    MAX_SPEED,
    SERVO_LEFT_MAX,
    SERVO_RIGHT_MAX,
    SERVO_STRAIGHT,
    STOP_SIGNAL,
    TURN_SPEED_FACTOR,
    UDP_IP,
    UDP_PORT,
    close_socket,
    ensure_socket,
    send_car_command as transmit_car_command,
)
from ai.vision_l1 import VisionLevel1, camera_index_from_env
from ai.voice_l1 import VoiceLevel1

# --- Global Configuration ---
CYCLE_TIME = 0.1
DEBUG_MODE = False

# Track the steering state globally. SERVO_STRAIGHT comes from ai.transport.
current_steering_angle = SERVO_STRAIGHT

# ERC_LOG_ONLY=1 (or the UI dry-run box) prints L/R/B/S and does not transmit.
LOG_ONLY = os.environ.get("ERC_LOG_ONLY", "").strip().lower() in {"1", "true", "yes", "on"}

try:
    ensure_socket()
except socket.error as e:
    print(f"Failed to create socket: {e}")
    sys.exit(1)

# --- Block Functions ---

def send_car_command(speed, steering_angle, stop_override=0, dry_run=None):
    """Send one ``L:,R:,B:,S:`` datagram to the ERC car.

    ``dry_run`` None follows ``LOG_ONLY`` (env ``ERC_LOG_ONLY`` or the UI
    checkbox). True logs the datagram and does not touch the socket.
    The student SDK calls ``ai.transport.send_car_command`` directly so it
    does not import this Qt module. Block programs keep calling this wrapper.
    """
    if dry_run is None:
        dry_run = LOG_ONLY
    return transmit_car_command(
        speed,
        steering_angle,
        stop_override,
        dry_run=dry_run,
        debug=DEBUG_MODE,
    )

def block_move_forward(duration_s=1, log_callback=None):
    if log_callback:
        log_callback(f"--> Command: Move Forward at angle {current_steering_angle} for {duration_s}s")
    # Use global steering angle so it keeps the turn set by the previous block
    send_car_command(FORWARD_SPEED, current_steering_angle)
    time.sleep(duration_s)
    send_car_command(0, current_steering_angle, STOP_SIGNAL)
    
def block_move_backward(duration_s=1, log_callback=None):
    if log_callback:
        log_callback(f"--> Command: Move Backward at angle {current_steering_angle} for {duration_s}s")
    # Use global steering angle
    send_car_command(-BACKWARD_SPEED, current_steering_angle)
    time.sleep(duration_s)
    send_car_command(0, current_steering_angle, STOP_SIGNAL)

def block_turn_angle(angle_degrees=0, log_callback=None):
    """Updates the wheel direction. Car stays still. Angle persists until changed."""
    global current_steering_angle
    
    if log_callback:
        log_callback(f"--> Command: Setting Steering Angle to {angle_degrees} degrees")
    
    # Calculate mapping from degrees to servo PWM
    if angle_degrees > 0:
        target_servo = SERVO_STRAIGHT + int((angle_degrees / 90.0) * (SERVO_RIGHT_MAX - SERVO_STRAIGHT))
        target_servo = min(target_servo, SERVO_RIGHT_MAX)
    elif angle_degrees < 0:
        target_servo = SERVO_STRAIGHT + int((angle_degrees / 90.0) * (SERVO_STRAIGHT - SERVO_LEFT_MAX))
        target_servo = max(target_servo, SERVO_LEFT_MAX)
    else:
        target_servo = SERVO_STRAIGHT
    
    # Update the global state
    current_steering_angle = target_servo
    
    # Send command with 0 speed (so car doesn't move) and the new angle
    send_car_command(0, current_steering_angle)
    
    # Give the physical servo a moment to reach the position
    time.sleep(0.3)
    # Note: We do NOT send a second command to reset here. 
    # The wheels will stay at 'current_steering_angle' until another block changes it.

def block_stop(log_callback=None):
    if log_callback:
        log_callback("--> Command: STOP")
    # Stop motors but maintain the current wheel angle
    send_car_command(0, current_steering_angle, STOP_SIGNAL)

def block_wait(duration_s=1, log_callback=None):
    if log_callback:
        log_callback(f"--> Command: Wait for {duration_s} seconds")
    send_car_command(0, current_steering_angle, STOP_SIGNAL)
    time.sleep(duration_s)


# --- Puzzle Piece Block Widget ---
class PuzzleBlock(QWidget):
    """A custom widget that looks like a puzzle piece block."""
    deleteRequested = pyqtSignal(int)
    
    def __init__(self, text, block_type, default_value=None, param_type=None, block_index=0, parent=None):
        super().__init__(parent)
        self.block_index = block_index
        self.block_type = block_type  # "Motion" or "Control"
        self.param_type = param_type  # "duration", "angle", or None
        self.default_value = default_value
        self.is_highlighted = False
        
        # Colors - ERC Racing Theme (Red and Yellow)
        if block_type == "Motion":
            self.bg_color = QColor(220, 20, 60)  # Racing Red
            self.border_color = QColor(139, 0, 0)  # Dark Red
            self.light_color = QColor(255, 99, 71)  # Lighter red for highlight
        else:
            self.bg_color = QColor(218, 165, 32)  # Darker Gold/Amber - easier to read
            self.border_color = QColor(139, 101, 8)  # Darker Gold border
            self.light_color = QColor(255, 200, 0)  # Less bright yellow for highlight
        
        # Different sizing for palette vs program blocks
        if block_index == -1:
            # Palette blocks - wider to show full text
            self.setMinimumSize(280, 75)
            self.setMaximumSize(280, 75)
        else:
            # Program blocks
            self.setMinimumSize(500, 75)
            self.setMaximumHeight(75)
            self.setFixedHeight(75)
        self.drag_start_position = QPoint()
        # Tab/notch visibility - will be set based on position
        self.show_top_tab = (block_index > 0)  # No tab for first block
        self.show_bottom_notch = True  # Will be updated when blocks are added/removed
        
        # Layout
        layout = QHBoxLayout(self)
        # More padding for palette blocks to show text clearly
        if block_index == -1:
            layout.setContentsMargins(12, 8, 12, 8)
        else:
            layout.setContentsMargins(15, 10, 15, 10)
        
        # Text label - Racing theme font with better contrast
        self.label = QLabel(text)
        # Use darker text on yellow blocks for better readability
        text_color = "#000000" if block_type == "Control" else "white"
        # Use consistent font for all blocks - slightly smaller in palette
        font_size = 15 if block_index == -1 else 17
        # For palette blocks, ensure text is fully visible with proper sizing
        if block_index == -1:
            self.label.setStyleSheet(f"""
                color: {text_color}; 
                font-family: 'Arial Black', 'Arial', 'Helvetica', sans-serif;
                font-weight: bold; 
                font-size: {font_size}px; 
                background: transparent;
                padding: 6px;
            """)
            self.label.setWordWrap(True)
            self.label.setAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            self.label.setMinimumWidth(250)
            self.label.setMaximumWidth(260)
        else:
            self.label.setStyleSheet(f"""
                color: {text_color}; 
                font-family: 'Arial Black', 'Arial', 'Helvetica', sans-serif;
                font-weight: bold; 
                font-size: {font_size}px; 
                background: transparent;
                padding: 4px;
            """)
            self.label.setWordWrap(True)
        layout.addWidget(self.label)
        
        # Parameter input if needed
        self.param_entry = None
        if param_type == "duration":
            self.param_entry = QLineEdit()
            self.param_entry.setFixedWidth(70)
            self.param_entry.setText(str(default_value) if default_value else "1")
            self.param_entry.setStyleSheet("""
                background: white; 
                border: 3px solid #DC143C; 
                border-radius: 5px; 
                padding: 5px;
                font-family: 'Arial Black', 'Arial', sans-serif;
                font-size: 15px;
                font-weight: bold;
                color: #8B0000;
            """)
            layout.addWidget(self.param_entry)
            unit_label = QLabel("seconds")
            # Use darker text on yellow blocks
            text_color = "#000000" if block_type == "Control" else "white"
            unit_label.setStyleSheet(f"""
                color: {text_color}; 
                font-family: 'Arial Black', 'Arial', sans-serif;
                font-size: 15px; 
                font-weight: bold;
                background: transparent;
            """)
            layout.addWidget(unit_label)
        elif param_type == "angle":
            self.param_entry = QLineEdit()
            self.param_entry.setFixedWidth(70)
            self.param_entry.setText(str(default_value) if default_value else "0")
            # Border color based on block type
            border_color = "#8B6914" if block_type == "Control" else "#DC143C"
            self.param_entry.setStyleSheet(f"""
                background: white; 
                border: 3px solid {border_color}; 
                border-radius: 5px; 
                padding: 5px;
                font-family: 'Arial Black', 'Arial', sans-serif;
                font-size: 15px;
                font-weight: bold;
                color: #8B0000;
            """)
            layout.addWidget(self.param_entry)
            unit_label = QLabel("degrees")
            # Use darker text on yellow blocks
            text_color = "#000000" if block_type == "Control" else "white"
            unit_label.setStyleSheet(f"""
                color: {text_color}; 
                font-family: 'Arial Black', 'Arial', sans-serif;
                font-size: 15px; 
                font-weight: bold;
                background: transparent;
            """)
            layout.addWidget(unit_label)
            help_label = QLabel("(Left: -, Right: +)")
            help_label.setStyleSheet(f"""
                color: {text_color}; 
                font-family: 'Arial', 'Helvetica', sans-serif;
                font-size: 13px; 
                font-weight: bold;
                font-style: italic;
                background: transparent;
            """)
            layout.addWidget(help_label)
        
        layout.addStretch()
    
    def paintEvent(self, event):
        """Draw the puzzle piece shape - Spike Prime style with proper connections."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        rect = self.rect()
        width = rect.width()
        height = rect.height()
        
        # Create puzzle piece path - Spike Prime style with better tabs
        path = QPainterPath()
        
        # Tab dimensions - consistent for proper connection
        tab_width = 60
        tab_height = 20
        corner_radius = 12
        
        # Start from top-left with rounded corner
        path.moveTo(corner_radius, 0)
        
        # Top edge - with or without tab
        if self.show_top_tab:
            # Top edge (with tab in center)
            path.lineTo(width/2 - tab_width/2, 0)
            # Top tab - rounded like puzzle piece
            # Left curve of tab
            path.quadTo(width/2 - tab_width/2 + 8, -tab_height/3, width/2 - tab_width/3, -tab_height*2/3)
            path.quadTo(width/2 - tab_width/6, -tab_height, width/2, -tab_height)
            # Right curve of tab
            path.quadTo(width/2 + tab_width/6, -tab_height, width/2 + tab_width/3, -tab_height*2/3)
            path.quadTo(width/2 + tab_width/2 - 8, -tab_height/3, width/2 + tab_width/2, 0)
        else:
            # Straight top edge (first block)
            path.lineTo(width - corner_radius, 0)
        
        # Continue top edge
        if self.show_top_tab:
            path.lineTo(width - corner_radius, 0)
        
        # Top-right corner
        path.arcTo(width - corner_radius*2, 0, corner_radius*2, corner_radius*2, 90, -90)
        # Right edge
        path.lineTo(width, height - corner_radius)
        # Bottom-right corner
        path.arcTo(width - corner_radius*2, height - corner_radius*2, corner_radius*2, corner_radius*2, 0, -90)
        
        # Bottom edge - with or without notch
        if self.show_bottom_notch:
            # Bottom edge (with notch in center)
            path.lineTo(width/2 + tab_width/2, height)
            # Bottom notch - inverted tab (matches top tab of next block)
            path.quadTo(width/2 + tab_width/2 - 8, height + tab_height/3, width/2 + tab_width/3, height + tab_height*2/3)
            path.quadTo(width/2 + tab_width/6, height + tab_height, width/2, height + tab_height)
            path.quadTo(width/2 - tab_width/6, height + tab_height, width/2 - tab_width/3, height + tab_height*2/3)
            path.quadTo(width/2 - tab_width/2 + 8, height + tab_height/3, width/2 - tab_width/2, height)
        else:
            # Straight bottom edge (last block)
            path.lineTo(corner_radius, height)
        
        # Continue bottom edge
        if self.show_bottom_notch:
            path.lineTo(corner_radius, height)
        
        # Bottom-left corner
        path.arcTo(0, height - corner_radius*2, corner_radius*2, corner_radius*2, -90, -90)
        # Left edge
        path.lineTo(0, corner_radius)
        # Top-left corner
        path.arcTo(0, 0, corner_radius*2, corner_radius*2, 180, -90)
        path.closeSubpath()
        
        # Fill with block color - Racing theme with gradient
        if self.is_highlighted:
            # Bright red when executing (racing highlight)
            highlight_gradient = QBrush(QColor(255, 0, 0))
            painter.fillPath(path, highlight_gradient)
        else:
            # Create a gradient for depth
            gradient = QBrush(self.bg_color)
            painter.fillPath(path, gradient)
            # Add a lighter highlight on top for 3D effect
            highlight_path = QPainterPath()
            highlight_path.addRoundedRect(3, 3, width - 6, 20, 8, 8)
            painter.fillPath(highlight_path, self.light_color)
        
        # Draw border - Racing theme with thicker border
        pen = QPen(self.border_color, 5)
        painter.setPen(pen)
        painter.drawPath(path)
        
        # Add racing stripe effect on top
        if not self.is_highlighted:
            stripe_path = QPainterPath()
            stripe_path.addRoundedRect(5, 5, width - 10, 8, 3, 3)
            painter.fillPath(stripe_path, self.light_color)
        
        # Add inner shadow for depth
        pen = QPen(QColor(0, 0, 0, 50), 2)
        painter.setPen(pen)
        inner_path = QPainterPath()
        inner_path.addRoundedRect(4, 4, width - 8, height - 8, corner_radius - 4, corner_radius - 4)
        painter.drawPath(inner_path)
    
    def get_param_value(self):
        """Get the parameter value from the entry field."""
        if self.param_entry:
            try:
                return float(self.param_entry.text())
            except ValueError:
                return self.default_value if self.default_value else (1 if self.param_type == "duration" else 0)
        return None
    
    def set_highlighted(self, highlighted):
        """Set highlight state."""
        self.is_highlighted = highlighted
        self.update()
    
    def mousePressEvent(self, event):
        """Handle mouse press for dragging."""
        if event.button() == Qt.LeftButton:
            self.drag_start_position = event.pos()
        super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event):
        """Handle mouse move for dragging."""
        if not (event.buttons() & Qt.LeftButton):
            return
        
        if not hasattr(self, 'drag_start_position'):
            return
        
        if ((event.pos() - self.drag_start_position).manhattanLength() < 
            QApplication.startDragDistance()):
            return
        
        # Allow dragging from both palette and program blocks
        drag = QDrag(self)
        mime_data = QMimeData()
        
        # Store block data - extract name properly (remove " for", " by", and parameter placeholders)
        label_text = self.label.text()
        # Remove parameter placeholders and connectors
        name = label_text
        if ' _' in label_text:
            name = label_text.split(' _')[0]
        elif ' (' in label_text:
            name = label_text.split(' (')[0]
        
        # Remove " for" and " by" connectors that might be in the text
        name = name.replace(' for', '').replace(' by', '').strip()
        
        # Store block data as a simple string format
        default_val_str = str(self.default_value) if self.default_value is not None else 'None'
        param_type_str = str(self.param_type) if self.param_type is not None else 'None'
        
        # Include block_index to identify if it's from program area (for deletion)
        block_data_str = f"{name}|{self.block_type}|{param_type_str}|{default_val_str}|{self.block_index}"
        mime_data.setData('application/x-block-data', block_data_str.encode('utf-8'))
        
        # If dragging from program area, mark it as a delete operation
        if self.block_index != -1:
            mime_data.setData('application/x-block-delete', b'delete')
        
        drag.setMimeData(mime_data)
        
        # Create drag pixmap with transparency
        pixmap = self.grab()
        drag.setPixmap(pixmap)
        drag.setHotSpot(event.pos())
        
        # Execute drag
        result = drag.exec_(Qt.CopyAction | Qt.MoveAction)
        
        # If moved and it's from program area, it was deleted
        if result == Qt.MoveAction and self.block_index != -1:
            # Signal will be handled by drop area
            pass


# --- Drop Area Widget ---
class DropArea(QWidget):
    """Widget that accepts drag and drop."""
    drop_signal = pyqtSignal(dict, int)  # block_data, insert_index
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.main_window = parent
    
    def dragEnterEvent(self, event):
        """Handle drag enter event."""
        if event.mimeData().hasFormat('application/x-block-data'):
            # Accept both new blocks and blocks being deleted
            event.acceptProposedAction()
            # Visual feedback for deletion - Racing theme
            if event.mimeData().hasFormat('application/x-block-delete'):
                self.setStyleSheet("""
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 #DAA520, stop:1 #FF4500);
                    border: 3px dashed #DC143C;
                    border-radius: 5px;
                """)
        else:
            event.ignore()
    
    def dragMoveEvent(self, event):
        """Handle drag move event."""
        if event.mimeData().hasFormat('application/x-block-data'):
            event.acceptProposedAction()
        else:
            event.ignore()
    
    def dragLeaveEvent(self, event):
        """Reset style when drag leaves."""
        # Reset to default racing theme
        if hasattr(self, 'main_window') and hasattr(self.main_window, 'program_widget'):
            if self == self.main_window.program_widget:
                self.setStyleSheet("")
            else:
                self.setStyleSheet("")
        else:
            self.setStyleSheet("")
        super().dragLeaveEvent(event)
    
    def get_insert_index(self, y_pos):
        """Determine where to insert the block based on Y position."""
        if not hasattr(self.main_window, 'program_blocks') or not self.main_window.program_blocks:
            return 0
        
        # Get the layout
        layout = self.layout()
        if not layout:
            return len(self.main_window.program_blocks)
        
        # Find which block position this Y coordinate corresponds to
        for i in range(layout.count() - 1):  # -1 to exclude stretch
            item = layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                widget_top = widget.y()
                widget_bottom = widget_top + widget.height()
                widget_center = widget_top + widget.height() / 2
                
                # If dropped above the center of this block, insert before it
                if y_pos < widget_center:
                    return i
        
        # If we get here, insert at the end
        return len(self.main_window.program_blocks)
    
    def dropEvent(self, event):
        """Handle drop event."""
        if event.mimeData().hasFormat('application/x-block-data'):
            try:
                data = event.mimeData().data('application/x-block-data')
                data_str = bytes(data.data()).decode('utf-8')
                parts = data_str.split('|')
                
                if len(parts) >= 4:
                    # Check if this is a delete operation (dragging from program area)
                    if event.mimeData().hasFormat('application/x-block-delete'):
                        # This is a delete - get block index
                        block_index = int(parts[4]) if len(parts) >= 5 else -1
                        if block_index >= 0:
                            QTimer.singleShot(0, lambda idx=block_index: self.main_window.delete_block(idx))
                            event.acceptProposedAction()
                            return
                    
                    # Parse default_value
                    default_val = None
                    if parts[3] and parts[3] != 'None':
                        try:
                            default_val = float(parts[3])
                        except ValueError:
                            default_val = None
                    
                    block_data = {
                        'name': parts[0],
                        'block_type': parts[1],
                        'param_type': parts[2] if parts[2] != 'None' else None,
                        'default_value': default_val
                    }
                    
                    # Get the Y position relative to this widget
                    y_pos = event.pos().y()
                    insert_index = self.get_insert_index(y_pos)
                    
                    # Use QTimer to ensure this happens in the main thread
                    QTimer.singleShot(0, lambda: self.drop_signal.emit(block_data, insert_index))
                    event.acceptProposedAction()
                else:
                    print(f"Invalid block data format: {parts}")
                    event.ignore()
            except Exception as e:
                print(f"Error handling drop: {e}")
                import traceback
                traceback.print_exc()
                event.ignore()
        else:
            event.ignore()

# --- Main Window ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.program_blocks = []
        self.is_executing = False
        self.execution_thread = None
        
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle("🏎️ ERC Racing Car - Block Programming")
        self.setGeometry(100, 100, 1400, 980)
        
        # Set racing theme background with checkered pattern effect
        self.setStyleSheet("""
            QMainWindow {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #DAA520, stop:0.3 #FF8C00, stop:0.7 #FF4500, stop:1 #DC143C);
            }
        """)
        
        # Central widget with horizontal split
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        central_widget.setStyleSheet("""
            QWidget {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #FFF8DC, stop:1 #FFE4E1);
            }
        """)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # Create horizontal splitter: Left = Palette, Right = Program Area
        splitter = QSplitter(Qt.Horizontal)
        
        # LEFT SIDE: Block Palette
        palette_container = QWidget()
        palette_container_layout = QVBoxLayout(palette_container)
        palette_container_layout.setContentsMargins(5, 5, 5, 5)
        
        palette_label = QLabel("🏁 Block Palette 🏁\nDrag blocks to program area\nDrag program blocks here to delete")
        palette_label.setStyleSheet("""
            font-size: 15px; 
            font-weight: bold; 
            font-family: 'Arial Black', 'Arial', sans-serif;
            padding: 12px; 
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #FFD700, stop:1 #FF4500);
            color: white;
            border: 3px solid #DC143C;
            border-radius: 8px;
        """)
        palette_label.setWordWrap(True)
        palette_container_layout.addWidget(palette_label)
        
        # Make palette accept drops for deletion
        palette_delete_area = DropArea(self)
        palette_delete_area.main_window = self
        palette_delete_area.setAcceptDrops(True)
        
        palette_scroll = QScrollArea()
        palette_scroll.setWidgetResizable(True)
        palette_scroll.setStyleSheet("""
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #FFF8DC, stop:1 #FFE4E1);
            border: 3px solid #DC143C;
            border-radius: 5px;
        """)
        
        palette_widget = QWidget()
        palette_layout = QVBoxLayout(palette_widget)
        palette_layout.setAlignment(Qt.AlignTop)
        palette_layout.setSpacing(8)  # Reduced spacing for better visibility
        palette_layout.setContentsMargins(5, 5, 5, 5)
        
        # Define blocks
        self.block_definitions = [
            ("Moving Forward", block_move_forward, 1, "Motion", "duration"),
            ("Moving Backward", block_move_backward, 1, "Motion", "duration"),
            ("Relative Position", block_turn_angle, 0, "Motion", "angle"),
            ("Wait", block_wait, 1, "Control", "duration"),
            ("Stop", block_stop, None, "Control", None),
        ]
        
        for name, func, default_val, block_type, param_type in self.block_definitions:
            palette_block = PuzzleBlock(name, block_type, default_val, param_type, -1)
            # Make palette blocks wider to show full text clearly - ensure it matches minimum size
            palette_block.setFixedSize(280, 75)
            # Set proper text for palette - show full description
            display_text = name
            if param_type == "duration":
                display_text = name + " for _ seconds"
            elif param_type == "angle":
                display_text = name + " by _ degrees"
            else:
                display_text = name
            
            # Update label with proper text and ensure it's visible with consistent font
            palette_block.label.setText(display_text)
            palette_block.label.setWordWrap(True)
            palette_block.label.setAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            
            # Ensure consistent font styling for palette blocks - override any previous styling
            text_color = "#000000" if block_type == "Control" else "white"
            palette_block.label.setStyleSheet(f"""
                color: {text_color}; 
                font-family: 'Arial Black', 'Arial', 'Helvetica', sans-serif;
                font-weight: bold; 
                font-size: 15px; 
                background: transparent;
                padding: 6px;
                min-width: 250px;
            """)
            # Ensure label can expand to show full text
            palette_block.label.setMinimumWidth(250)
            
            # Hide parameter entry in palette
            if palette_block.param_entry:
                palette_block.param_entry.hide()
            
            # Hide unit labels in palette since we show them in the text
            for child in palette_block.findChildren(QLabel):
                if child != palette_block.label and child.text() in ["seconds", "degrees", "(Left: -, Right: +)"]:
                    child.hide()
            
            palette_block.setCursor(Qt.PointingHandCursor)
            palette_layout.addWidget(palette_block)
        
        palette_layout.addStretch()
        palette_scroll.setWidget(palette_widget)
        
        # Wrap scroll area in delete area
        palette_delete_area_layout = QVBoxLayout(palette_delete_area)
        palette_delete_area_layout.setContentsMargins(0, 0, 0, 0)
        palette_delete_area_layout.addWidget(palette_scroll)
        palette_container_layout.addWidget(palette_delete_area)
        
        splitter.addWidget(palette_container)
        splitter.setStretchFactor(0, 1)  # Palette takes 1/3
        
        # RIGHT SIDE: Program Area
        program_container = QWidget()
        program_container_layout = QVBoxLayout(program_container)
        program_container_layout.setContentsMargins(5, 5, 5, 5)
        
        program_label = QLabel("🏎️ Program Area 🏎️\nDrag blocks here to build your racing program")
        program_label.setStyleSheet("""
            font-size: 17px; 
            font-weight: bold; 
            font-family: 'Arial Black', 'Arial', sans-serif;
            padding: 12px; 
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #DC143C, stop:1 #FF4500);
            color: white;
            border: 3px solid #DAA520;
            border-radius: 8px;
        """)
        program_label.setWordWrap(True)
        program_container_layout.addWidget(program_label)
        
        # Scroll area for program blocks with drop support
        self.program_scroll = QScrollArea()
        self.program_scroll.setWidgetResizable(True)
        self.program_scroll.setStyleSheet("""
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #FFE4E1, stop:1 #FFF8DC);
            border: 3px solid #DAA520;
            border-radius: 5px;
        """)
        
        self.program_widget = DropArea(self)
        self.program_widget.main_window = self
        self.program_widget.drop_signal.connect(self.handle_drop)
        self.program_layout = QVBoxLayout(self.program_widget)
        self.program_layout.setAlignment(Qt.AlignTop)
        self.program_layout.setSpacing(0)  # No spacing so tabs/notches connect properly
        self.program_layout.addStretch()
        
        self.program_scroll.setWidget(self.program_widget)
        program_container_layout.addWidget(self.program_scroll, 1)
        
        # Control buttons
        button_layout = QHBoxLayout()
        
        self.run_button = QPushButton("🏁 START RACE")
        self.run_button.setStyleSheet("""
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #FFD700, stop:1 #FF8C00);
            color: white; 
            font-weight: bold; 
            font-family: 'Arial Black', 'Arial', sans-serif;
            padding: 12px 25px; 
            font-size: 16px;
            border: 3px solid #DC143C;
            border-radius: 8px;
        """)
        self.run_button.clicked.connect(self.run_program)
        button_layout.addWidget(self.run_button)
        
        self.stop_button = QPushButton("🛑 STOP")
        self.stop_button.setStyleSheet("""
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #DC143C, stop:1 #8B0000);
            color: white; 
            font-weight: bold; 
            font-family: 'Arial Black', 'Arial', sans-serif;
            padding: 12px 25px; 
            font-size: 16px;
            border: 3px solid #DAA520;
            border-radius: 8px;
        """)
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_program)
        button_layout.addWidget(self.stop_button)
        
        button_layout.addStretch()
        
        clear_button = QPushButton("🗑️ Clear Track")
        clear_button.setStyleSheet("""
            padding: 10px 20px; 
            font-size: 13px;
            font-weight: bold;
            font-family: 'Arial', sans-serif;
            background: #FFE4E1;
            border: 2px solid #DC143C;
            border-radius: 5px;
        """)
        clear_button.clicked.connect(self.clear_program)
        button_layout.addWidget(clear_button)
        
        log_toggle = QPushButton("📋 Race Log")
        log_toggle.setStyleSheet("""
            padding: 8px 15px; 
            font-size: 12px;
            font-weight: bold;
            background: #FFE4E1;
            border: 2px solid #DC143C;
            border-radius: 5px;
        """)
        log_toggle.clicked.connect(lambda: self.log_text.setVisible(not self.log_text.isVisible()))
        button_layout.addWidget(log_toggle)
        
        program_container_layout.addLayout(button_layout)

        # Log area (hidden by default) - Racing theme. Created before the AI
        # panel so gateway messages can use self.log.
        self.log_text = QTextEdit()
        self.log_text.setMaximumHeight(150)
        self.log_text.setStyleSheet("""
            background: #FFF8DC; 
            border: 3px solid #DAA520; 
            font-family: 'Courier New', monospace; 
            font-size: 10px;
            border-radius: 5px;
            color: #8B0000;
        """)
        self.log_text.hide()
        self._build_ai_panel()
        program_container_layout.addWidget(self.ai_panel)
        program_container_layout.addWidget(self.log_text)
        
        splitter.addWidget(program_container)
        splitter.setStretchFactor(1, 2)  # Program area takes 2/3
        
        main_layout.addWidget(splitter, 1)
        
        self.log("🏎️ ERC Racing Car Controller Initialized! 🏎️")
        self.log("UDP commands to {}:{}".format(UDP_IP, UDP_PORT))
        self.log("🏁 Drag blocks from the palette to build your racing program! 🏁")
        if LOG_ONLY:
            self.log("Dry run: ERC_LOG_ONLY is set. Datagrams are logged and not sent.")
        self.log("Level 1 AI is off until Vision AI or Voice AI is enabled. E-stop and block programs override AI.")
        self._ai_timer.start()
    
    def handle_drop(self, block_data, insert_index):
        """Handle block drop from palette."""
        self.add_block(block_data=block_data, insert_index=insert_index)
    
    def log(self, msg):
        """Add message to log."""
        self.log_text.append(msg)
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())
        print(msg)
    
    def add_block(self, name=None, func=None, default_val=None, block_type=None, param_type=None, block_data=None, insert_index=None):
        """Add a block to the program."""
        try:
            if self.is_executing:
                self.log("Cannot modify program while it's running.")
                return
            
            # Support both direct call and drag-drop
            if block_data:
                name = block_data.get('name', '')
                # Clean the name - remove " for" and " by" connectors
                name = name.replace(' for', '').replace(' by', '').strip()
                block_type = block_data.get('block_type', 'Motion')
                param_type = block_data.get('param_type', None)
                default_val = block_data.get('default_value', None)
                # Find the function from definitions
                func = None
                for n, f, d, bt, pt in self.block_definitions:
                    if n == name and bt == block_type and pt == param_type:
                        func = f
                        break
                
                if func is None:
                    self.log(f"Error: Could not find function for block '{name}' (type: {block_type}, param: {param_type})")
                    self.log(f"Available blocks: {[n for n, _, _, bt, pt in self.block_definitions]}")
                    return
            
            if not name or not block_type:
                self.log("Error: Invalid block data")
                return
            
            # Determine insertion index
            if insert_index is None:
                insert_index = len(self.program_blocks)
            else:
                insert_index = min(insert_index, len(self.program_blocks))
            
            block = PuzzleBlock(name, block_type, default_val, param_type, insert_index)
            block.deleteRequested.connect(self.delete_block)
            
            # Insert at the specified position
            self.program_blocks.insert(insert_index, (block, func, param_type))
            
            # Update all block indices and tab/notch visibility
            for i, (b, _, _) in enumerate(self.program_blocks):
                b.block_index = i
                # First block: no top tab
                b.show_top_tab = (i > 0)
                # Last block: no bottom notch
                b.show_bottom_notch = (i < len(self.program_blocks) - 1)
                b.update()  # Redraw with new tab/notch settings
            
            # Insert widget at the correct position in layout (before stretch)
            layout_count = self.program_layout.count()
            if insert_index >= layout_count - 1:
                # Insert before stretch
                self.program_layout.insertWidget(layout_count - 1, block)
            else:
                # Insert at specific position
                self.program_layout.insertWidget(insert_index, block)
            
            self.log(f"Added block: {name} at position {insert_index}")
        except Exception as e:
            self.log(f"Error adding block: {e}")
            import traceback
            traceback.print_exc()
    
    def delete_block(self, index):
        """Delete a block from the program."""
        if self.is_executing:
            self.log("Cannot modify program while it's running.")
            return
        
        if 0 <= index < len(self.program_blocks):
            block, _, _ = self.program_blocks[index]
            # Remove from layout
            self.program_layout.removeWidget(block)
            block.deleteLater()
            del self.program_blocks[index]
            
            # Update indices and tab/notch visibility
            for i, (b, _, _) in enumerate(self.program_blocks):
                b.block_index = i
                # First block: no top tab
                b.show_top_tab = (i > 0)
                # Last block: no bottom notch
                b.show_bottom_notch = (i < len(self.program_blocks) - 1)
                b.update()  # Redraw with new tab/notch settings
            
            self.log(f"Deleted block at position {index}")
    
    def clear_program(self):
        """Clear all blocks."""
        if self.is_executing:
            self.log("Cannot clear program while it's running.")
            return
        
        for block, _, _ in self.program_blocks:
            block.deleteLater()
        self.program_blocks.clear()
        self.log("Program cleared.")
    
    def run_program(self):
        """Run the program. Refuses while e-stop is latched."""
        if self.is_executing:
            return
        if self.gateway.estop_latched:
            self.log("E-stop is latched. Press Clear e-stop before running the program.")
            return

        # Manual blocks own the wire until execute_program's finally.
        self.gateway.set_manual_override(True)
        self.is_executing = True
        self.run_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        
        self.execution_thread = threading.Thread(target=self.execute_program)
        self.execution_thread.daemon = True
        self.execution_thread.start()
    
    def execute_program(self):
        """Execute the program sequence."""
        self.log("--- Starting Program Execution ---")
        
        try:
            for i, (block, func, param_type) in enumerate(self.program_blocks):
                if not self.is_executing:
                    break
                
                # Highlight current block
                block.set_highlighted(True)
                QApplication.processEvents()
                
                # Get parameter value
                param_value = block.get_param_value()
                
                # Execute block
                if param_type == "duration":
                    func(param_value, log_callback=self.log)
                elif param_type == "angle":
                    func(param_value, log_callback=self.log)
                else:
                    func(log_callback=self.log)
                
                if not self.is_executing:
                    break
                
                time.sleep(0.1)
                
                # Remove highlight
                block.set_highlighted(False)
                QApplication.processEvents()
        
        except Exception as e:
            self.log(f"Error during execution: {e}")
        finally:
            self.log("--- Program Execution Finished ---")
            send_car_command(0, SERVO_STRAIGHT, STOP_SIGNAL)
            self.gateway.acknowledge_external_stop()
            self.is_executing = False
            self.gateway.set_manual_override(False)
            self.run_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            
            # Clear all highlights
            for block, _, _ in self.program_blocks:
                block.set_highlighted(False)
            QApplication.processEvents()
    
    def stop_program(self):
        """Stop program execution and latch e-stop so AI cannot resume."""
        self.is_executing = False
        self.log("Stopping program (e-stop).")
        self.gateway.emergency_stop("ui")
        self._refresh_ai_status()

    def _build_ai_panel(self):
        """Vision / voice toggles. Block buttons above this panel are unchanged."""
        self.gateway = CommandGateway(
            send_car_command,
            forward_speed=FORWARD_SPEED,
            turn_speed=int(FORWARD_SPEED * TURN_SPEED_FACTOR),
            servo_straight=SERVO_STRAIGHT,
            servo_left=SERVO_LEFT_MAX,
            servo_right=SERVO_RIGHT_MAX,
            stop_signal=STOP_SIGNAL,
            stall_timeout_s=stall_timeout_from_env(),
            log=self.log,
        )
        self.vision = VisionLevel1(camera_index=camera_index_from_env())
        self.voice = VoiceLevel1()
        self._vision_seen_ts = None

        self.ai_panel = QFrame()
        self.ai_panel.setObjectName("aiPanel")
        self.ai_panel.setStyleSheet(
            "QFrame#aiPanel { background-color: #FFF8DC; border: 3px solid #8B0000; border-radius: 8px; }"
        )
        panel_layout = QVBoxLayout(self.ai_panel)
        panel_layout.setContentsMargins(10, 8, 10, 8)
        panel_layout.setSpacing(6)

        title = QLabel("Level 1 AI  —  vision and voice share L/R/B/S. Manual blocks and E-STOP win.")
        title.setStyleSheet(self._ai_label_style())
        title.setWordWrap(True)
        panel_layout.addWidget(title)

        toggles = QHBoxLayout()
        self.vision_button = QPushButton("Vision AI: OFF")
        self.vision_button.setCheckable(True)
        self.vision_button.toggled.connect(self._toggle_vision)
        toggles.addWidget(self.vision_button)

        self.voice_button = QPushButton("Voice AI: OFF")
        self.voice_button.setCheckable(True)
        self.voice_button.toggled.connect(self._toggle_voice)
        toggles.addWidget(self.voice_button)

        self.dry_run_box = QCheckBox("Dry run (log only, no UDP)")
        self.dry_run_box.setChecked(LOG_ONLY)
        self.dry_run_box.setStyleSheet(self._ai_label_style())
        self.dry_run_box.toggled.connect(self._toggle_dry_run)
        toggles.addWidget(self.dry_run_box)
        toggles.addStretch()
        panel_layout.addLayout(toggles)
        self._style_ai_toggle(self.vision_button, False)
        self._style_ai_toggle(self.voice_button, False)

        sim_row = QHBoxLayout()
        sim_label = QLabel("Vision input:")
        sim_label.setStyleSheet(self._ai_label_style())
        sim_row.addWidget(sim_label)
        self.sim_combo = QComboBox()
        self.sim_combo.addItem("Camera", "camera")
        self.sim_combo.addItem("Simulate green (forward)", "green")
        self.sim_combo.addItem("Simulate red (stop)", "red")
        self.sim_combo.addItem("Simulate blue (left)", "blue")
        self.sim_combo.addItem("Simulate yellow (right)", "yellow")
        self.sim_combo.addItem("Simulate none", "none")
        self.sim_combo.currentIndexChanged.connect(self._on_sim_changed)
        sim_row.addWidget(self.sim_combo)
        sim_row.addStretch()
        panel_layout.addLayout(sim_row)

        voice_row = QHBoxLayout()
        self.voice_entry = QLineEdit()
        self.voice_entry.setPlaceholderText('Voice text: forward, stop, left, right, emergency stop')
        self.voice_entry.returnPressed.connect(self._submit_voice)
        voice_row.addWidget(self.voice_entry)
        send_voice = QPushButton("Send voice")
        send_voice.clicked.connect(self._submit_voice)
        voice_row.addWidget(send_voice)
        mic_once = QPushButton("Mic once")
        mic_once.clicked.connect(self._mic_once)
        voice_row.addWidget(mic_once)
        panel_layout.addLayout(voice_row)

        self.ai_detect_label = QLabel("Last label: —    Last intent: —")
        self.ai_detect_label.setStyleSheet(self._ai_label_style())
        self.ai_detect_label.setWordWrap(True)
        panel_layout.addWidget(self.ai_detect_label)

        self.ai_command_label = QLabel("Last command: —")
        self.ai_command_label.setStyleSheet(
            "color: #8B0000; background-color: #FFF8DC; "
            "font-family: 'Courier New', monospace; font-size: 13px; font-weight: bold;"
        )
        self.ai_command_label.setWordWrap(True)
        panel_layout.addWidget(self.ai_command_label)

        self.ai_safety_label = QLabel("Safety: AI off")
        self.ai_safety_label.setStyleSheet(self._ai_label_style())
        self.ai_safety_label.setWordWrap(True)
        panel_layout.addWidget(self.ai_safety_label)

        estop_row = QHBoxLayout()
        estop_button = QPushButton("E-STOP")
        estop_button.setStyleSheet(
            "background: #8B0000; color: white; font-weight: bold; padding: 8px 18px; border-radius: 6px;"
        )
        estop_button.clicked.connect(self.stop_program)
        estop_row.addWidget(estop_button)
        clear_estop = QPushButton("Clear e-stop")
        clear_estop.setStyleSheet(
            "background: #FFF8DC; color: #1a1a1a; font-weight: bold; padding: 8px 18px; "
            "border: 2px solid #8B0000; border-radius: 6px;"
        )
        clear_estop.clicked.connect(self._clear_estop)
        estop_row.addWidget(clear_estop)
        estop_row.addStretch()
        panel_layout.addLayout(estop_row)

        self._ai_timer = QTimer(self)
        self._ai_timer.setInterval(100)
        self._ai_timer.timeout.connect(self._on_ai_tick)

    def _ai_label_style(self):
        return (
            "color: #1a1a1a; background-color: #FFF8DC; font-weight: bold; font-size: 13px;"
        )

    def _style_ai_toggle(self, button, on):
        if on:
            button.setStyleSheet(
                "background: #228B22; color: white; font-weight: bold; padding: 8px 14px; border-radius: 6px;"
            )
        else:
            button.setStyleSheet(
                "background: #EEE8AA; color: #1a1a1a; font-weight: bold; padding: 8px 14px; "
                "border: 2px solid #8B0000; border-radius: 6px;"
            )

    def _toggle_dry_run(self, checked):
        global LOG_ONLY
        LOG_ONLY = bool(checked)
        if checked:
            self.log("Dry run ON — L/R/B/S is logged, UDP is not sent.")
        else:
            self.log("Dry run OFF — commands are sent to {}:{}.".format(UDP_IP, UDP_PORT))

    def _toggle_vision(self, checked):
        self.vision_button.setText("Vision AI: ON" if checked else "Vision AI: OFF")
        self._style_ai_toggle(self.vision_button, checked)
        self.vision.set_mode(self.sim_combo.currentData())
        if checked:
            self._vision_seen_ts = None
            self.vision.start()
        else:
            self.vision.stop()
        self.gateway.set_source_enabled("vision", checked)
        self._refresh_ai_status()

    def _toggle_voice(self, checked):
        self.voice_button.setText("Voice AI: ON" if checked else "Voice AI: OFF")
        self._style_ai_toggle(self.voice_button, checked)
        self.gateway.set_source_enabled("voice", checked)
        self._refresh_ai_status()

    def _on_sim_changed(self, _index):
        mode = self.sim_combo.currentData()
        self.vision.set_mode(mode if mode else "camera")

    def _submit_voice(self):
        text = self.voice_entry.text().strip()
        if not text:
            return
        intent = self.voice.transcript_to_intent(text)
        if intent is None:
            self.log(f"No Level 1 intent in {text!r}. Try forward, stop, left, right, emergency stop.")
            self.gateway.last_label = text
            self.gateway.last_intent = "—"
            self._refresh_ai_status()
            return
        self.gateway.submit_intent(intent, source="voice", label=text)
        self._refresh_ai_status()

    def _mic_once(self):
        text = self.voice.listen_once()
        if not text:
            backend = self.voice.backend_name or "none"
            self.log(
                f"Mic once: ASR is not capturing (backend={backend}). "
                "Type a command and press Send voice. TODO(C3): speech_recognition or Vosk."
            )
            return
        self.voice_entry.setText(text)
        self._submit_voice()

    def _clear_estop(self):
        self.gateway.clear_estop()
        self._refresh_ai_status()

    def _on_ai_tick(self):
        try:
            if self.vision_button.isChecked():
                ts, label, intent = self.vision.latest()
                if ts is not None and ts != self._vision_seen_ts:
                    self._vision_seen_ts = ts
                    shown = label if label else "none"
                    if intent:
                        self.gateway.submit_intent(intent, source="vision", label=shown)
                    else:
                        self.gateway.heartbeat("vision", label=shown)
            self.gateway.tick()
            self._refresh_ai_status()
        except Exception as exc:
            self.log(f"AI tick error: {exc}")

    def _refresh_ai_status(self):
        gateway = self.gateway
        self.ai_detect_label.setText(
            f"Last label: {gateway.last_label}    Last intent: {gateway.last_intent}"
        )
        self.ai_command_label.setText(f"Last command: {gateway.last_command}")
        source = self.vision.status_message if self.vision_button.isChecked() else "off"
        self.ai_safety_label.setText(
            f"Safety: {gateway.safety_status()}    Vision source: {source}"
        )

    def closeEvent(self, event):
        """Handle window close. Brake wins over any in-flight AI intent."""
        self.is_executing = False
        if hasattr(self, "_ai_timer"):
            self._ai_timer.stop()
        if hasattr(self, "vision"):
            self.vision.stop()
        if hasattr(self, "gateway"):
            self.gateway.emergency_stop("close")
        else:
            send_car_command(0, SERVO_STRAIGHT, STOP_SIGNAL)
        close_socket()
        event.accept()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


