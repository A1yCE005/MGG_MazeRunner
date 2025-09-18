# -*- coding: utf-8 -*-
"""
MazeBot - simple inheritance state machine (stable Init->Prepare)
- Unifies template types (BGRA/GRAY -> BGR/GRAY 8U) to avoid OpenCV assertion
- Uses mss for window-region capture
- States: Init, Prepare, Route_Selection, Route_Confirmation, (Boss_)Battle, Relic_Selection, Shop, Support
"""

from __future__ import annotations
import os, time
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, List

import cv2
import numpy as np
import pyautogui
import pygetwindow as gw
from mss import mss


# ---------------- utils ----------------
@dataclass
class MatchResult:
    key: str
    maxv: float
    tl: Tuple[int, int]
    br: Tuple[int, int]
    center: Tuple[int, int]


def clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)


# --------------- core bot ---------------
class MazeBot:
    def __init__(self, hwnd_title: str, templates_dir: str, log, param_provider, debug: bool = False):
        self.hwnd_title = hwnd_title or ""
        self.templates_dir = templates_dir or os.path.join(os.getcwd(), "templates")
        self.log = log or print
        self._param_provider = param_provider
        self.debug = bool(debug)

        self._stop = False
        self.win = None
        self._bbox: Dict[str, int] | None = None
        self._current_state: Optional[State_Base] = None

        # template caches (BGR / GRAY 8U)
        self._tpl_gray: Dict[str, np.ndarray] = {}
        self._tpl_color: Dict[str, np.ndarray] = {}

        pyautogui.FAILSAFE = False  # Disable corner fail-safe

        self._update_runtime_params()
        self._load_templates()

    # ---------- params ----------
    def _update_runtime_params(self):
        p = self._param_provider() or {}
        # Thresholds
        self.thr_main = float(p.get("thr_main", 0.76))
        self.thr_tag = float(p.get("thr_tag", 0.77))
        self.thr_skip_color = float(p.get("thr_skip_color", 0.64))
        # Timing (already in seconds)
        self.sleep_base = max(0.006, float(p.get("sleep_base", 0.03)))
        self.sleep_fast = max(0.006, float(p.get("sleep_fast", 0.02)))
        # Width of selectable area on the left
        self.route_left_ratio = clamp01(float(p.get("route_left_ratio", 0.56)))

        # Event priority (configurable)
        default_priority = "event_boss,event_risky,event_battle,event_support,event_shop,event_event,event_unknown"
        raw = p.get("event_priority", default_priority)
        if isinstance(raw, str):
            self.event_priority = [x.strip() for x in raw.split(",") if x.strip()]
        elif isinstance(raw, list):
            self.event_priority = [str(x).strip() for x in raw if str(x).strip()]
        else:
            self.event_priority = [x.strip() for x in default_priority.split(",")]

    # ---------- templates ----------
    def _load_templates(self):
        cnt = 0
        if not os.path.isdir(self.templates_dir):
            self.log(f"[ERR] template directory missing: {self.templates_dir}")
            return
        for fn in os.listdir(self.templates_dir):
            if not fn.lower().endswith(".png"):
                continue
            key = os.path.splitext(fn)[0]
            path = os.path.join(self.templates_dir, fn)
            raw = cv2.imread(path, cv2.IMREAD_UNCHANGED)
            if raw is None:
                continue

            # COLOR: normalize to BGR 8U three channels
            if raw.ndim == 3 and raw.shape[2] == 4:
                color = cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)
            elif raw.ndim == 3 and raw.shape[2] == 3:
                color = raw
            else:
                color = cv2.cvtColor(raw, cv2.COLOR_GRAY2BGR)

            # GRAY: single channel 8U
            if raw.ndim == 3 and raw.shape[2] == 4:
                gray = cv2.cvtColor(raw, cv2.COLOR_BGRA2GRAY)
            elif raw.ndim == 3 and raw.shape[2] == 3:
                gray = cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY)
            else:
                gray = raw

            self._tpl_color[key] = color
            self._tpl_gray[key] = gray
            cnt += 1

        if self.debug:
            self.log(f"[DEBUG] Loaded {cnt} templates from {self.templates_dir}")

    # ---------- window & capture ----------
    def _ensure_window(self):
        titles = [t for t in gw.getAllTitles() if self.hwnd_title in t]
        if not titles:
            raise RuntimeError(f"Window not found: {self.hwnd_title}")
        win = gw.getWindowsWithTitle(titles[0])[0]
        try:
            win.activate()
            time.sleep(0.15)
        except Exception:
            pass
        self.win = win
        self._bbox = {
            "left": int(win.left),
            "top": int(win.top),
            "width": int(win.width),
            "height": int(win.height),
        }
        if self.debug:
            self.log(f"[DEBUG] Bound: {titles[0]} @ {win.left},{win.top} {win.width}x{win.height}")

    def _grab(self) -> Tuple[np.ndarray, Dict[str, int]]:
        if self._bbox is None:
            self._ensure_window()
        b = self._bbox
        with mss() as sct:
            shot = sct.grab({"left": b["left"], "top": b["top"], "width": b["width"], "height": b["height"]})
        img = np.array(shot)[:, :, :3]  # BGRA -> BGR
        return img, b

    # ---------- roi / click ----------
    def _roi_abs(self, roi: Tuple[float, float, float, float]) -> Tuple[int, int, int, int]:
        b = self._bbox
        L = b["left"] + int(b["width"] * clamp01(roi[0]))
        T = b["top"] + int(b["height"] * clamp01(roi[1]))
        R = b["left"] + int(b["width"] * clamp01(roi[2]))
        B = b["top"] + int(b["height"] * clamp01(roi[3]))
        return L, T, R, B

    def click_abs(self, pt: Tuple[int, int], duration: float = 0.02):
        x, y = int(pt[0]), int(pt[1])
        pyautogui.moveTo(x, y, duration=duration)
        pyautogui.click()
        if self.debug:
            self.log(f"[CLICK] {x},{y}")

    # ---------- matching ----------
    def _match_single(self, scr: np.ndarray, tpl: np.ndarray, thr: float) -> Optional[Tuple[float, Tuple[int, int]]]:
        res = cv2.matchTemplate(scr, tpl, cv2.TM_CCOEFF_NORMED)
        minv, maxv, minl, maxl = cv2.minMaxLoc(res)
        if maxv >= thr:
            return maxv, maxl
        return None

    def _match_gray(self, screen: np.ndarray, key: str, thr: float) -> Optional[MatchResult]:
        tpl = self._tpl_gray.get(key)
        if tpl is None:
            return None
        scr = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        hit = self._match_single(scr, tpl, thr)
        if not hit:
            return None
        maxv, tl = hit
        h, w = tpl.shape[:2]
        tl_abs = (self._bbox["left"] + tl[0], self._bbox["top"] + tl[1])
        br_abs = (tl_abs[0] + w, tl_abs[1] + h)
        center = (tl_abs[0] + w // 2, tl_abs[1] + h // 2)
        return MatchResult(key, maxv, tl_abs, br_abs, center)

    def _match_color(self, screen: np.ndarray, key: str, thr: float) -> Optional[MatchResult]:
        tpl = self._tpl_color.get(key)
        if tpl is None:
            return None
        hit = self._match_single(screen, tpl, thr)
        if not hit:
            return None
        maxv, tl = hit
        h, w = tpl.shape[:2]
        tl_abs = (self._bbox["left"] + tl[0], self._bbox["top"] + tl[1])
        br_abs = (tl_abs[0] + w, tl_abs[1] + h)
        center = (tl_abs[0] + w // 2, tl_abs[1] + h // 2)
        return MatchResult(key, maxv, tl_abs, br_abs, center)

    def _match_roi(self, screen: np.ndarray, key: str, thr: float,
                   roi: Tuple[float, float, float, float], use_color: bool = False) -> Optional[MatchResult]:
        L, T, R, B = self._roi_abs(roi)
        sub = screen[T - self._bbox["top"]: B - self._bbox["top"], L - self._bbox["left"]: R - self._bbox["left"]]
        if sub.size <= 0:
            return None
        if use_color:
            tpl = self._tpl_color.get(key)
            if tpl is None:
                return None
            hit = self._match_single(sub, tpl, thr)
        else:
            tpl = self._tpl_gray.get(key)
            if tpl is None:
                return None
            subg = cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY)
            hit = self._match_single(subg, tpl, thr)
        if not hit:
            return None
        maxv, tl = hit
        h, w = tpl.shape[:2]
        tl_abs = (L + tl[0], T + tl[1])
        br_abs = (tl_abs[0] + w, tl_abs[1] + h)
        center = (tl_abs[0] + w // 2, tl_abs[1] + h // 2)
        return MatchResult(key, maxv, tl_abs, br_abs, center)

    # ---------- lifecycle ----------
    def start(self):
        self._stop = False
        self._ensure_window()
        self._update_runtime_params()

        # Preload frequently used templates
        for k in [
            "btn_explore", "btn_explore_confirm", "tag_select", "btn_shop_skip",
            "title_route", "btn_route_confirm",
            "btn_battle_skip", "btn_next",
            "title_relic", "relic_diamond",
            "event_battle", "event_risky", "event_boss", "event_support", "event_shop", "event_event", "event_unknown"
        ]:
            _ = self._tpl_gray.get(k, None)
            if _ is None:
                _ = self._tpl_color.get(k, None)

        self._current_state = Init_State(self)
        if self.debug:
            self.log("[INFO] bot started")

    def stop(self):
        self._stop = True
        self.log("[INFO] stopped")

    def loop(self):
        self._update_runtime_params()
        if self._current_state is None:
            self.start()
        while not self._stop:
            nxt = self._current_state.run()
            if nxt is not None:
                self._current_state = nxt
            else:
                time.sleep(self.sleep_fast)


class State_Base:
    NAME = "BASE"
    TIMEOUT_SECS = 25

    def __init__(self, bot: MazeBot, after: list[type["State_Base"]] | None = None):
        self.bot = bot
        self.after = list(after) if after else []
        self._t0 = time.time()
        self._last = 0.0
        self._beat = 0

    def warmup(self, keys: List[str]):
        for k in keys:
            _ = self.bot._tpl_gray.get(k, None)
            if _ is None:
                _ = self.bot._tpl_color.get(k, None)

    def heartbeat(self) -> bool:
        now = time.time()
        if now - self._last >= 1.0:
            self._last = now
            self._beat += 1
            if self.bot.debug:
                self.bot.log(f"[STATE] {self.NAME} +{self._beat}s")
        return (now - self._t0) > self.TIMEOUT_SECS

    def next_from_chain(self) -> "State_Base":
        """Return the next state from the after chain; fallback to route selection when empty."""
        if self.after:
            cls = self.after[0]
            rest = self.after[1:]
            return cls(self.bot, after=rest)
        return Route_Selection_State(self.bot)

    def run(self) -> Optional["State_Base"]:
        raise NotImplementedError



# --------------- states ---------------
from maze_states import (
    Battle_State,
    Boss_Battle_State,
    Init_State,
    Prepare_State,
    Relic_Selection_State,
    Route_Confirmation_State,
    Route_Selection_State,
    Shop_State,
    Support_State,
)


