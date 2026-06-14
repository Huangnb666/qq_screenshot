import sys
import os
import uuid
from enum import Enum

# 【核心：防糊】强制开启 Windows 最高级别的 PerMonitorV2 DPI 感知，保证 1:1 像素绝对清晰
import ctypes
try:
    ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
except:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except:
        pass

from PyQt6.QtCore import Qt, QPoint, QRect, pyqtSignal, QObject, QStandardPaths
from PyQt6.QtWidgets import QApplication, QWidget, QHBoxLayout, QToolButton, QFileDialog, QMessageBox, QMenu, QLineEdit
from PyQt6.QtGui import QPixmap, QPainter, QPen, QColor, QGuiApplication, QAction, QPolygon, QBrush, QFontMetrics

# --- 全局贴图生命周期管理器（防止贴图窗口被 Python 自动垃圾回收） ---
GLOBAL_PINNED_WINDOWS = []

# --- 全局配置 ---
HOTKEY = 'alt+a'
DEFAULT_COLOR = QColor(255, 0, 0) # 默认标注红色
HANDLE_SIZE = 8 # 调整大小手柄的大小

class HotkeySignaler(QObject):
    activated = pyqtSignal()
    def __init__(self):
        super().__init__()
        import keyboard
        keyboard.add_hotkey(HOTKEY, self.activated.emit, suppress=True)

class ShapeType(Enum):
    RECT = 1
    ELLIPSE = 2
    ARROW = 3
    PEN = 4
    TEXT = 5
    SEQUENCE = 6 # 序号工具

class Annotation:
    def __init__(self, shape_type, color=DEFAULT_COLOR, width=2):
        self.shape_type = shape_type
        self.color = color
        self.width = width
        self.points = []
        self.text = ""           
        self.text_pos = QPoint() 

# --- 📌 钉在桌面置顶浮窗组件 ---
class PinnedWindow(QWidget):
    def __init__(self, pixmap, pos):
        super().__init__()
        # 置顶、无边框、独立工具窗口
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        self.pixmap = pixmap
        self.resize(pixmap.size())
        self.move(pos)
        
        self.drag_position = QPoint()
        self.show()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self.pixmap)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    def mouseDoubleClickEvent(self, event):
        # 双击直接关闭贴图
        self.close_and_clear()

    def contextMenuEvent(self, event):
        # 右键菜单
        menu = QMenu(self)
        menu.setStyleSheet("QMenu { background-color: #333333; color: white; border: 1px solid #555555; } QMenu::item:selected { background-color: #0078d7; }")
        
        close_action = menu.addAction("关闭 (双击)")
        close_action.triggered.connect(self.close_and_clear)
        
        save_action = menu.addAction("另存为...")
        save_action.triggered.connect(self.save_to_file)
        
        menu.exec(event.globalPos())

    def save_to_file(self):
        default_path = os.path.join(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation), "Pinned_Image.png")
        save_path, _ = QFileDialog.getSaveFileName(self, "贴图另存为", default_path, "PNG图片 (*.png);;JPG图片 (*.jpg)")
        if save_path:
            self.pixmap.save(save_path)

    def close_and_clear(self):
        self.close()
        if self in GLOBAL_PINNED_WINDOWS:
            GLOBAL_PINNED_WINDOWS.remove(self)

# --- 仿 QQ 精简工具栏 ---
class ScreenshotToolbar(QWidget):
    mode_changed = pyqtSignal(object) 
    action_triggered = pyqtSignal(str)     

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.SubWindow | Qt.WindowType.FramelessWindowHint)
        self.init_ui()

    def init_ui(self):
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("""
            QWidget { background-color: #333333; border-radius: 4px; padding: 2px; }
            QToolButton { color: white; background-color: transparent; border: none; padding: 6px 9px; margin: 1px; font-family: "Microsoft YaHei"; font-size: 13px; }
            QToolButton:hover { background-color: #555555; border-radius: 2px; }
            QToolButton:checked { background-color: #0078d7; border-radius: 2px; }
            QToolButton#btn_done { color: #00e070; font-weight: bold; font-size: 14px;}
            QToolButton#btn_cancel { color: #ff5555; }
        """)

        layout = QHBoxLayout()
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)

        # 标注工具组
        self.btn_rect = QToolButton(); self.btn_rect.setText("矩形")
        self.btn_ellipse = QToolButton(); self.btn_ellipse.setText("椭圆")
        self.btn_arrow = QToolButton(); self.btn_arrow.setText("箭头")
        self.btn_pen = QToolButton(); self.btn_pen.setText("画笔")
        self.btn_text = QToolButton(); self.btn_text.setText("文本")
        self.btn_seq = QToolButton(); self.btn_seq.setText("① 序号")

        for btn in [self.btn_rect, self.btn_ellipse, self.btn_arrow, self.btn_pen, self.btn_text, self.btn_seq]:
            btn.setCheckable(True)

        self.btn_rect.clicked.connect(lambda: self._toggle_tool(ShapeType.RECT, self.btn_rect))
        self.btn_ellipse.clicked.connect(lambda: self._toggle_tool(ShapeType.ELLIPSE, self.btn_ellipse))
        self.btn_arrow.clicked.connect(lambda: self._toggle_tool(ShapeType.ARROW, self.btn_arrow))
        self.btn_pen.clicked.connect(lambda: self._toggle_tool(ShapeType.PEN, self.btn_pen))
        self.btn_text.clicked.connect(lambda: self._toggle_tool(ShapeType.TEXT, self.btn_text))
        self.btn_seq.clicked.connect(lambda: self._toggle_tool(ShapeType.SEQUENCE, self.btn_seq))

        layout.addWidget(self.btn_rect); layout.addWidget(self.btn_ellipse)
        layout.addWidget(self.btn_arrow); layout.addWidget(self.btn_pen)
        layout.addWidget(self.btn_text); layout.addWidget(self.btn_seq)

        line = QWidget(); line.setFixedWidth(1); line.setStyleSheet("background-color: #555555; margin: 4px 2px;"); layout.addWidget(line)

        # 动作功能组
        self.btn_undo = QToolButton(); self.btn_undo.setText("撤销")
        self.btn_undo.clicked.connect(lambda: self.action_triggered.emit("undo"))
        
        self.btn_pin = QToolButton(); self.btn_pin.setText("📌 钉在桌面")
        self.btn_pin.clicked.connect(lambda: self.action_triggered.emit("pin"))
        
        self.btn_save = QToolButton(); self.btn_save.setText("保存")
        self.btn_save.clicked.connect(lambda: self.action_triggered.emit("save"))

        self.btn_more = QToolButton(); self.btn_more.setText("∨")
        self.more_menu = QMenu(self)
        self.act_save_as = QAction("另存为...", self)
        self.act_save_as.triggered.connect(lambda: self.action_triggered.emit("save_as"))
        self.more_menu.addAction(self.act_save_as)
        self.btn_more.setMenu(self.more_menu)
        self.btn_more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        self.btn_cancel = QToolButton(); self.btn_cancel.setText("× 取消"); self.btn_cancel.setObjectName("btn_cancel")
        self.btn_cancel.clicked.connect(lambda: self.action_triggered.emit("cancel"))

        self.btn_done = QToolButton(); self.btn_done.setText("✓ 完成"); self.btn_done.setObjectName("btn_done")
        self.btn_done.clicked.connect(lambda: self.action_triggered.emit("done"))

        layout.addWidget(self.btn_undo); layout.addWidget(self.btn_pin); layout.addWidget(self.btn_save)
        layout.addWidget(self.btn_more); layout.addWidget(self.btn_cancel); layout.addWidget(self.btn_done)
        self.setLayout(layout)

    def _toggle_tool(self, shape_type, target_btn):
        if target_btn.isChecked():
            for btn in [self.btn_rect, self.btn_ellipse, self.btn_arrow, self.btn_pen, self.btn_text, self.btn_seq]:
                if btn != target_btn: btn.setChecked(False)
            self.mode_changed.emit(shape_type)
        else:
            self.mode_changed.emit(None)

    def reset_tools(self):
        for btn in [self.btn_rect, self.btn_ellipse, self.btn_arrow, self.btn_pen, self.btn_text, self.btn_seq]:
            btn.setChecked(False)

# --- 主全屏画布 ---
class ScreenshotOverlay(QWidget):
    class State(Enum):
        WAITING = 0      
        SELECTING = 1    
        SELECTED = 2     
        MOVING = 3       
        RESIZING = 4     
        DRAWING = 5      

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        
        self._init_data()
        self.screen_pixmap = QPixmap() 
        self.text_editor = None 
        
        self.toolbar = ScreenshotToolbar(self)
        self.toolbar.hide()
        self.toolbar.mode_changed.connect(self.set_annotation_mode)
        self.toolbar.action_triggered.connect(self.handle_toolbar_action)

    def _init_data(self):
        self.state = self.State.WAITING
        self.current_annot_type = None 
        self.selection_rect = QRect() 
        self.annotations = []         
        self.drag_start_pos = QPoint()
        self.rect_at_drag_start = QRect()
        self.current_annot_obj = None
        self.resize_handle_index = -1 
        self.sequence_counter = 1 # 序号从 1 开始累加
        self.setCursor(Qt.CursorShape.CrossCursor)

    def capture_screen(self):
        self.commit_text_editor() 
        self._init_data()
        self.toolbar.reset_tools()
        self.toolbar.hide()

        screen = QGuiApplication.primaryScreen()
        if not screen: return
        
        device_ratio = screen.devicePixelRatio()
        self.setGeometry(screen.geometry()) 
        full_pix = screen.grabWindow(0)
        full_pix.setDevicePixelRatio(device_ratio)
        
        self.screen_pixmap = full_pix
        self.showFullScreen()
        self.activateWindow()

    def paintEvent(self, event):
        if self.screen_pixmap.isNull(): return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.drawPixmap(0, 0, self.screen_pixmap) # 1:1 无损输出

        mask_color = QColor(0, 0, 0, 110)
        if not self.selection_rect.isValid():
            painter.fillRect(self.rect(), mask_color)
        else:
            sel = self.selection_rect
            painter.fillRect(0, 0, self.width(), sel.top(), mask_color) 
            painter.fillRect(0, sel.bottom() + 1, self.width(), self.height() - sel.bottom(), mask_color) 
            painter.fillRect(0, sel.top(), sel.left(), sel.height(), mask_color) 
            painter.fillRect(sel.right() + 1, sel.top(), self.width() - sel.right(), sel.height(), mask_color) 

            border_pen = QPen(QColor(0, 140, 255), 2, Qt.PenStyle.SolidLine)
            painter.setPen(border_pen)
            painter.drawRect(sel)

            if self.state in (self.State.SELECTED, self.State.MOVING, self.State.RESIZING, self.State.DRAWING):
                self._draw_handles(painter)

        if self.selection_rect.isValid():
            painter.setClipRect(self.selection_rect) 
            for annot in self.annotations: self._draw_single_annotation(painter, annot)
            if self.current_annot_obj: self._draw_single_annotation(painter, self.current_annot_obj)
            painter.setClipping(False)

    def _draw_handles(self, painter):
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(0, 140, 255)))
        handles = self._get_handle_rects()
        for r in handles: painter.drawRect(r)

    def _get_handle_rects(self):
        if not self.selection_rect.isValid(): return []
        r = self.selection_rect
        s = HANDLE_SIZE; hs = s // 2
        coords = [
            (r.left(), r.top()), (r.center().x(), r.top()), (r.right(), r.top()),
            (r.right(), r.center().y()), (r.right(), r.bottom()), (r.center().x(), r.bottom()),
            (r.left(), r.bottom()), (r.left(), r.center().y())
        ]
        return [QRect(x - hs, y - hs, s, s) for x, y in coords]

    def _draw_single_annotation(self, painter, annot):
        # 1. 序号标签渲染
        if annot.shape_type == ShapeType.SEQUENCE:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(annot.color))
            radius = 12
            painter.drawEllipse(annot.text_pos, radius, radius) # 画实心圆圈
            
            painter.setPen(QPen(Qt.GlobalColor.white))
            font = painter.font(); font.setFamily("Microsoft YaHei"); font.setPointSize(10); font.setBold(True); painter.setFont(font)
            fm = QFontMetrics(font)
            tx = annot.text_pos.x() - fm.horizontalAdvance(annot.text) / 2
            ty = annot.text_pos.y() + fm.ascent() / 2 - 1
            painter.drawText(int(tx), int(ty), annot.text)
            return

        # 2. 文本标签渲染
        if annot.shape_type == ShapeType.TEXT:
            painter.setPen(QPen(annot.color))
            font = painter.font(); font.setFamily("Microsoft YaHei"); font.setPointSize(14); font.setBold(True); painter.setFont(font)
            fm = QFontMetrics(font)
            painter.drawText(annot.text_pos.x() + 3, annot.text_pos.y() + fm.ascent() + 2, annot.text)
            return

        # 3. 几何标注渲染
        painter.setPen(QPen(annot.color, annot.width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if annot.shape_type in (ShapeType.RECT, ShapeType.ELLIPSE, ShapeType.ARROW):
            if len(annot.points) < 2: return
            r = QRect(annot.points[0], annot.points[1]).normalized()
            if annot.shape_type == ShapeType.RECT: painter.drawRect(r)
            elif annot.shape_type == ShapeType.ELLIPSE: painter.drawEllipse(r)
            elif annot.shape_type == ShapeType.ARROW: self._draw_arrow(painter, annot.points[0], annot.points[1], annot.color, annot.width)
        elif annot.shape_type == ShapeType.PEN:
            if len(annot.points) < 2: return
            for i in range(len(annot.points) - 1): painter.drawLine(annot.points[i], annot.points[i+1])

    def _draw_arrow(self, painter, start, end, color, width):
        painter.drawLine(start, end)
        try:
            from math import atan2, pi, cos, sin
            angle = atan2(-(end.y() - start.y()), end.x() - start.x())
            arrow_size = 15 + width
            p1 = QPoint(int(end.x() - arrow_size * cos(angle - pi / 10)), int(end.y() + arrow_size * sin(angle - pi / 10)))
            p2 = QPoint(int(end.x() - arrow_size * cos(angle + pi / 10)), int(end.y() + arrow_size * sin(angle + pi / 10)))
            painter.setBrush(QBrush(color)); painter.setPen(Qt.PenStyle.NoPen); painter.drawPolygon(QPolygon([end, p1, p2])); painter.setBrush(Qt.BrushStyle.NoBrush) 
        except: pass

    def mousePressEvent(self, event):
        p = event.position().toPoint()
        if self.state == self.State.WAITING and event.button() == Qt.MouseButton.LeftButton:
            self.drag_start_pos = p; self.state = self.State.SELECTING; self.toolbar.hide()

        elif self.state == self.State.SELECTED and event.button() == Qt.MouseButton.LeftButton:
            if self.current_annot_type:
                if self.selection_rect.contains(p):
                    # 序号标注落点
                    if self.current_annot_type == ShapeType.SEQUENCE:
                        annot = Annotation(ShapeType.SEQUENCE)
                        annot.text = str(self.sequence_counter)
                        annot.text_pos = p
                        self.annotations.append(annot)
                        self.sequence_counter += 1
                        self.update()
                        return
                    
                    # 文本标注触发
                    if self.current_annot_type == ShapeType.TEXT:
                        self.commit_text_editor()
                        self.text_editor = QLineEdit(self)
                        self.text_editor.setStyleSheet("QLineEdit { background: transparent; color: red; border: 1px dashed red; font-family: 'Microsoft YaHei'; font-size: 14px; font-weight: bold; padding: 1px; }")
                        self.text_editor.move(p.x(), p.y()); self.text_editor.resize(100, 26); self.text_editor.setFocus()
                        self.text_editor.textChanged.connect(self._auto_resize_text_editor)
                        self.text_editor.returnPressed.connect(self.commit_text_editor)
                        self.text_editor.show()
                        self.text_spawn_pos = p
                        return
                    
                    # 几何绘图触发
                    self.state = self.State.DRAWING
                    self.current_annot_obj = Annotation(self.current_annot_type)
                    if self.current_annot_type == ShapeType.PEN: self.current_annot_obj.points.append(p)
                    else: self.current_annot_obj.points = [p, p]
                return

            handles = self._get_handle_rects()
            for i, r in enumerate(handles):
                if r.contains(p):
                    self.resize_handle_index = i; self.state = self.State.RESIZING; self.rect_at_drag_start = self.selection_rect; self.drag_start_pos = p; self.toolbar.hide(); return
            if self.selection_rect.contains(p):
                self.state = self.State.MOVING; self.rect_at_drag_start = self.selection_rect; self.drag_start_pos = p; self.setCursor(Qt.CursorShape.SizeAllCursor); self.toolbar.hide()
            else:
                self.selection_rect = QRect(); self._init_data(); self.toolbar.reset_tools(); self.toolbar.hide(); self.state = self.State.WAITING; self.update()

    def _auto_resize_text_editor(self, text):
        if self.text_editor:
            fm = QFontMetrics(self.text_editor.font())
            needed_w = max(100, fm.horizontalAdvance(text) + 15)
            max_w = self.selection_rect.right() - self.text_editor.x() - 5
            self.text_editor.resize(min(needed_w, max_w), 26)

    def commit_text_editor(self):
        if self.text_editor:
            content = self.text_editor.text().strip()
            if content:
                annot = Annotation(ShapeType.TEXT); annot.text = content; annot.text_pos = self.text_spawn_pos; self.annotations.append(annot)
            self.text_editor.deleteLater(); self.text_editor = None; self.update()

    def mouseMoveEvent(self, event):
        p = event.position().toPoint()
        if self.state == self.State.SELECTED:
            found_handle = False
            if not self.current_annot_type: 
                cursors = [Qt.CursorShape.SizeFDiagCursor, Qt.CursorShape.SizeVerCursor, Qt.CursorShape.SizeBDiagCursor, Qt.CursorShape.SizeHorCursor, Qt.CursorShape.SizeFDiagCursor, Qt.CursorShape.SizeVerCursor, Qt.CursorShape.SizeBDiagCursor, Qt.CursorShape.SizeHorCursor]
                for i, r in enumerate(self._get_handle_rects()):
                    if r.contains(p): self.setCursor(cursors[i]); found_handle = True; break
            if not found_handle: self.setCursor(Qt.CursorShape.CrossCursor if self.current_annot_type else Qt.CursorShape.SizeAllCursor) if self.selection_rect.contains(p) else self.setCursor(Qt.CursorShape.ArrowCursor)

        if self.state == self.State.SELECTING: self.selection_rect = QRect(self.drag_start_pos, p).normalized(); self.update()
        elif self.state == self.State.MOVING:
            dx = p.x() - self.drag_start_pos.x(); dy = p.y() - self.drag_start_pos.y(); new_r = self.rect_at_drag_start.translated(dx, dy)
            if new_r.left() < 0: new_r.moveLeft(0)
            if new_r.right() > self.width(): new_r.moveRight(self.width()-1)
            if new_r.top() < 0: new_r.moveTop(0)
            if new_r.bottom() > self.height(): new_r.moveBottom(self.height()-1)
            self.selection_rect = new_r; self.update()
        elif self.state == self.State.RESIZING:
            r = QRect(self.rect_at_drag_start); idx = self.resize_handle_index
            if idx in (0, 7, 6): r.setLeft(p.x())
            if idx in (2, 3, 4): r.setRight(p.x())
            if idx in (0, 1, 2): r.setTop(p.y())
            if idx in (4, 5, 6): r.setBottom(p.y())
            self.selection_rect = r.normalized(); self.update()
        elif self.state == self.State.DRAWING and self.current_annot_obj:
            if self.current_annot_type == ShapeType.PEN:
                safe_p = QPoint(max(self.selection_rect.left(), min(p.x(), self.selection_rect.right())), max(self.selection_rect.top(), min(p.y(), self.selection_rect.bottom())))
                self.current_annot_obj.points.append(safe_p)
            else: self.current_annot_obj.points[1] = p
            self.update()

    def mouseReleaseEvent(self, event):
        if self.state == self.State.SELECTING:
            if self.selection_rect.width() > 10 and self.selection_rect.height() > 10: self.state = self.State.SELECTED; self.show_toolbar(); self.update()
            else: self._init_data(); self.toolbar.hide(); self.update()
        elif self.state in (self.State.MOVING, self.State.RESIZING): self.state = self.State.SELECTED; self.setCursor(Qt.CursorShape.CrossCursor if self.current_annot_type else Qt.CursorShape.SizeAllCursor); self.show_toolbar(); self.update()
        elif self.state == self.State.DRAWING:
            if self.current_annot_obj:
                if self.current_annot_type == ShapeType.PEN or (len(self.current_annot_obj.points) > 1 and QPoint(self.current_annot_obj.points[0] - self.current_annot_obj.points[1]).manhattanLength() > 2): self.annotations.append(self.current_annot_obj)
            self.current_annot_obj = None; self.state = self.State.SELECTED; self.show_toolbar(); self.update()

    def show_toolbar(self):
        if not self.selection_rect.isValid(): return
        r = self.selection_rect; tw = self.toolbar.sizeHint().width(); th = self.toolbar.sizeHint().height()
        tx = r.right() - tw + 1
        if tx < 0: tx = 2
        ty = r.bottom() + 8
        if ty + th > self.height(): ty = r.top() - th - 8
        if ty < 0: ty = 2
        self.toolbar.move(tx, ty); self.toolbar.show()

    def set_annotation_mode(self, shape_type):
        self.commit_text_editor(); self.current_annot_type = shape_type
        if self.selection_rect.isValid(): self.setCursor(Qt.CursorShape.CrossCursor if shape_type else Qt.CursorShape.SizeAllCursor)

    def handle_toolbar_action(self, action_name):
        if action_name == "done": self.finish_screenshot(copy_to_clipboard=True)
        elif action_name == "save": self.finish_screenshot(copy_to_clipboard=False, save_to_file=True)
        elif action_name == "save_as": self.finish_screenshot(copy_to_clipboard=False, save_to_file=True, save_as=True)
        elif action_name == "pin": self.finish_screenshot(make_pinned=True) # 钉在桌面
        elif action_name == "undo":
            self.commit_text_editor()
            if self.annotations:
                popped = self.annotations.pop()
                if popped.shape_type == ShapeType.SEQUENCE: self.sequence_counter = max(1, self.sequence_counter - 1)
                self.update()
        elif action_name == "cancel": self.close_screenshot()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape: self.close_screenshot()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter): self.commit_text_editor() if self.text_editor else self.finish_screenshot(copy_to_clipboard=True)

    def close_screenshot(self):
        self.commit_text_editor(); self.toolbar.hide(); self.hide(); self._init_data()

    def finish_screenshot(self, copy_to_clipboard=False, save_to_file=False, save_as=False, make_pinned=False):
        self.commit_text_editor()
        if not self.selection_rect.isValid(): self.close_screenshot(); return

        final_img = self.screen_pixmap.copy(self.selection_rect)
        if self.annotations:
            composed_pix = QPixmap(final_img)
            painter = QPainter(composed_pix); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            offset = self.selection_rect.topLeft(); painter.translate(-offset)
            painter.setClipRect(QRect(offset, self.selection_rect.size())) 
            for annot in self.annotations: self._draw_single_annotation(painter, annot)
            painter.end(); final_img = composed_pix

        if make_pinned:
            # 固化最终合并好的图片并开启贴图窗口
            pinned_win = PinnedWindow(final_img, self.selection_rect.topLeft())
            GLOBAL_PINNED_WINDOWS.append(pinned_win)
            self.close_screenshot()
        elif copy_to_clipboard:
            QGuiApplication.clipboard().setPixmap(final_img); self.close_screenshot()
        elif save_to_file:
            self._save_to_file_dialog(final_img, save_as)

    def _save_to_file_dialog(self, pixmap, save_as=False):
        default_folder = r"D:\截图"
        try:
            if not os.path.exists(default_folder): os.makedirs(default_folder, exist_ok=True)
        except:
            default_folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)

        filename = f"Screenshot_{uuid.uuid4().hex[:8]}.png"
        default_path = os.path.join(default_folder, filename)

        if save_as:
            save_path, _ = QFileDialog.getSaveFileName(self, "截图另存为", default_path, "PNG图片 (*.png);;JPG图片 (*.jpg)")
            if save_path and pixmap.save(save_path): self.close_screenshot()
        else:
            if pixmap.save(default_path): self.close_screenshot()
            else: QMessageBox.critical(self, "错误", f"无法保存截图到 {default_path}")

if __name__ == "__main__":
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    overlay = ScreenshotOverlay()
    try:
        hotkey_signaler = HotkeySignaler()
        hotkey_signaler.activated.connect(overlay.capture_screen)
        print(f"🚀 1:1 原生高清极简版启动！[Alt + A] 唤醒。")
    except Exception as e:
        sys.exit(1)
    sys.exit(app.exec())