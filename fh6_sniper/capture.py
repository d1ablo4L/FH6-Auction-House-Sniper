"""Screen capture and window-focus helpers."""
from __future__ import annotations
import logging
import time
import numpy as np
import cv2
import win32con
import win32gui

_log = logging.getLogger("fh6.capture")

CANON = (1920, 1080)

_camera = None
_camera_unavailable = False
_hwnd_cache: dict = {}


def find_window(title: str) -> int:
    """Return the hwnd of a visible window with this title, or 0."""
    cached = _hwnd_cache.get(title)
    if cached and win32gui.IsWindow(cached):
        return cached
    matches = []

    def _collect(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            if win32gui.GetWindowText(hwnd).strip() == title:
                matches.append(hwnd)

    win32gui.EnumWindows(_collect, None)
    hwnd = matches[0] if matches else 0
    if hwnd:
        _hwnd_cache[title] = hwnd
    return hwnd


def client_rect(hwnd: int):
    """Return (left, top, width, height) of a window's client area."""
    cl, ct, cr, cb = win32gui.GetClientRect(hwnd)
    width, height = cr - cl, cb - ct
    sx, sy = win32gui.ClientToScreen(hwnd, (cl, ct))
    return sx, sy, width, height


def using_dxgi() -> bool:
    return _camera is not None and not _camera_unavailable


def _grab_dxgi(region):
    global _camera, _camera_unavailable
    if _camera_unavailable:
        return None
    try:
        import bettercam
        if _camera is None:
            _camera = bettercam.create(output_idx=0, output_color="BGR")
        for _ in range(5):
            frame = _camera.grab(region=region) if region else _camera.grab()
            if frame is not None:
                return np.ascontiguousarray(frame)
            time.sleep(0.008)
        return None
    except Exception:
        _camera_unavailable = True
        return None


def _grab_mss(region):
    import mss
    with mss.MSS() as sct:
        if region:
            area = {"left": region[0], "top": region[1],
                    "width": region[2] - region[0],
                    "height": region[3] - region[1]}
        else:
            area = sct.monitors[1]
        shot = sct.grab(area)
        return np.ascontiguousarray(np.array(shot)[:, :, :3])


_capture_failing = False


def grab_screen(window_title: str | None = None) -> np.ndarray:
    """Capture a BGR 1920x1080 frame. Falls back to mss on DXGI failure;
    returns a blank frame if both backends fail."""
    global _capture_failing
    region = None
    if window_title:
        hwnd = find_window(window_title)
        if hwnd:
            x, y, w, h = client_rect(hwnd)
            if w > 0 and h > 0:
                region = (x, y, x + w, y + h)
    frame = _grab_dxgi(region)
    if frame is None:
        try:
            frame = _grab_mss(region)
        except Exception as e:
            if not _capture_failing:
                _log.warning("capture failed: %s", e)
                _capture_failing = True
            frame = None
    if frame is None:
        return np.zeros((CANON[1], CANON[0], 3), dtype=np.uint8)
    if _capture_failing:
        _log.info("capture recovered")
        _capture_failing = False
    if (frame.shape[1], frame.shape[0]) != CANON:
        frame = cv2.resize(frame, CANON, interpolation=cv2.INTER_AREA)
    return frame


def foreground_title() -> str:
    return win32gui.GetWindowText(win32gui.GetForegroundWindow())


def is_game_focused(expected_title: str, title_getter=foreground_title) -> bool:
    return title_getter().strip() == expected_title


def focus_window(title: str) -> bool:
    """Bring the named window to the foreground. Returns True on success."""
    hwnd = find_window(title)
    if not hwnd:
        return False
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False
