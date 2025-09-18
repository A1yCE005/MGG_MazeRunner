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
            self.log(f"[ERR] 模板目录不存在: {self.templates_dir}")
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
            self.log("[INFO] 机器人启动")

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


# --------------- states ---------------
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
        """按 after 链返回下一个状态；若链为空则回到路线选择"""
        if self.after:
            cls = self.after[0]
            rest = self.after[1:]
            return cls(self.bot, after=rest)
        return Route_Selection_State(self.bot)

    def run(self) -> Optional["State_Base"]:
        raise NotImplementedError



class Init_State(State_Base):
    NAME = "Init"
    TIMEOUT_SECS = 15

    def run(self):
        b = self.bot
        b._ensure_window()

        while not b._stop:
            if self.heartbeat():
                # On timeout return to route selection to avoid idling
                return Route_Selection_State(b)

            scr, _ = b._grab()

            # On the Prepare/Formation screen
            if (b._match_gray(scr, "btn_explore", b.thr_main) or
                b._match_gray(scr, "btn_explore_confirm", b.thr_main) or
                b._match_color(scr, "btn_explore_confirm", b.thr_main) or
                b._match_gray(scr, "tag_select", b.thr_tag)):
                return Prepare_State(b)

            # Fallback: click bottom-right Next (e.g. after reward popup)
            nxt = b._match_gray(scr, "btn_next", b.thr_main)
            if nxt:
                b.click_abs(nxt.center)
                time.sleep(b.sleep_fast * 1.1)
                continue

            # Direct jumps handled per screen already
            if b._match_gray(scr, "title_route", b.thr_tag):
                return Route_Selection_State(b)
            if b._match_gray(scr, "btn_route_confirm", b.thr_main):
                return Route_Confirmation_State(b)
            if b._match_gray(scr, "btn_battle_skip", b.thr_main):
                return Battle_State(b)
            if b._match_gray(scr, "title_relic", b.thr_tag):
                # Fix: class name should be Relic_Selection_State
                return Relic_Selection_State(b)

            time.sleep(b.sleep_fast)
        return None


class Prepare_State(State_Base):
    NAME = "Prepare"
    TIMEOUT_SECS = 15

    def run(self):
        b = self.bot
        self.warmup(["btn_explore", "btn_explore_confirm", "tag_select"])

        clicked_explore = False
        while not b._stop:
            if self.heartbeat():
                return Init_State(b)

            scr, _ = b._grab()

            # Click Select/Begin exploration first
            if not clicked_explore:
                hit = (b._match_gray(scr, "btn_explore", b.thr_main) or
                       b._match_color(scr, "btn_explore", b.thr_main))
                if hit:
                    b.click_abs(hit.center)
                    clicked_explore = True
                    time.sleep(b.sleep_base)
                    continue

            # Then click Confirm
            ok = (b._match_gray(scr, "btn_explore_confirm", b.thr_main) or
                  b._match_color(scr, "btn_explore_confirm", b.thr_main))
            if not ok:
                # Fallback ROI at bottom right
                ok = b._match_roi(scr, "btn_explore_confirm", b.thr_main, (0.65, 0.80, 0.98, 0.98), use_color=True)

            if ok:
                b.click_abs(ok.center)
                time.sleep(b.sleep_fast * 1.2)
                return Route_Selection_State(b)

            if b._match_gray(scr, "title_route", b.thr_tag):
                return Route_Selection_State(b)

            time.sleep(b.sleep_fast)
        return None


class Route_Selection_State(State_Base):
    NAME = "Route_Select"
    TIMEOUT_SECS = 20

    def _try_match(self, scr, key, roi, thr):
        b = self.bot
        # Try grayscale before color fallback; use whichever hits first
        return (b._match_roi(scr, key, thr, roi) or
                b._match_roi(scr, key, thr, roi, use_color=True))

    def _collect_eligible(self, scr, roi):
        b = self.bot
        ok = []
        for name in b.event_priority:
            r = self._try_match(scr, name, roi, b.thr_main)
            if r:
                ok.append((name, r.maxv, r.center))
        return ok

    def _scan_debug_hits(self, scr, roi):
        b = self.bot
        keys = ("event_boss","event_risky","event_battle","event_support",
                "event_shop","event_event","event_unknown")
        hits = []
        thr_dbg = max(0.50, b.thr_main - 0.25)
        for k in keys:
            r = (b._match_roi(scr, k, thr_dbg, roi) or
                 b._match_roi(scr, k, thr_dbg, roi, use_color=True))
            if r:
                hits.append((k, r.maxv, r.center))
        hits.sort(key=lambda x: x[1], reverse=True)
        return hits[:8]

    def _pick(self, scr):
        b = self.bot
        left = max(0.05, min(0.75, b.route_left_ratio))
        roi1 = (0.05, 0.18, left, 0.86)
        # Pass 1: standard ROI
        for name in b.event_priority:
            r = self._try_match(scr, name, roi1, b.thr_main)
            if r:
                return r.center, name, roi1
        # Pass 2: enlarged ROI fallback
        roi2 = (0.02, 0.12, min(0.78, left + 0.12), 0.90)
        for name in b.event_priority:
            r = self._try_match(scr, name, roi2, b.thr_main - 0.02)
            if r:
                return r.center, name, roi2
        return None

    def run(self):
        b = self.bot
        self.warmup(["title_route", "btn_route_confirm",
                     "event_boss","event_battle","event_risky",
                     "event_support","event_shop","event_event","event_unknown"])

        dbg_last = 0.0
        while not b._stop:
            if self.heartbeat():
                return Init_State(b)

            scr, _ = b._grab()
            title_r = b._match_gray(scr, "title_route", max(0.5, b.thr_tag - 0.15))
            on_route = title_r is not None

            if not on_route:
                # Skip destination checks for non-route screens
                if b._match_gray(scr, "btn_battle_skip", b.thr_main):
                    return Battle_State(b)
                if b._match_gray(scr, "title_relic", b.thr_tag):
                    return Relic_Selection_State(b)
                if b._match_gray(scr, "btn_route_confirm", b.thr_main):
                    return Route_Confirmation_State(b)
                return Init_State(b)

            # On the route screen: emit debug output
            left = max(0.05, min(0.75, b.route_left_ratio))
            roi = (0.05, 0.18, left, 0.86)
            if b.debug and time.time() - dbg_last > 0.7:
                b.log(f"[ROUTE/DBG] title_route={title_r.maxv:.2f} | roi={roi} | left_ratio={left:.2f}")
                b.log(f"[ROUTE/DBG] priority={b.event_priority}")
                # What is visible (loose threshold)
                for kk, vv, cc in self._scan_debug_hits(scr, roi):
                    b.log(f"[ROUTE/DBG] seen {kk:>12s} v={vv:.2f} @ {cc}")
                # Which options are actually selectable (strict threshold)
                elig = self._collect_eligible(scr, roi)
                if elig:
                    txt = ", ".join([f"{k}:{v:.2f}@{c}" for k, v, c in elig])
                else:
                    txt = "(none)"
                b.log(f"[ROUTE/DBG] eligible={txt}")
                dbg_last = time.time()

            picked = self._pick(scr)
            if picked:
                (cx, cy), key, used_roi = picked
                if b.debug:
                    b.log(f"[ROUTE] choose {key} @ {(cx, cy)} (roi={used_roi})")
                b.click_abs((cx, cy))
                time.sleep(b.sleep_fast)
                battle_cls = Boss_Battle_State if key == "event_boss" else Battle_State
                return Route_Confirmation_State(b, battle_cls=battle_cls)

            time.sleep(b.sleep_fast)



class Route_Confirmation_State(State_Base):
    NAME = "Route_Confirm"
    TIMEOUT_SECS = 10

    def __init__(self, bot: MazeBot, after: list[type["State_Base"]] | None = None,
                 battle_cls: type[State_Base] | None = None):
        super().__init__(bot, after)
        # Fix: default cannot forward reference undefined class in signature
        from typing import cast
        self.battle_cls = cast(type[State_Base], battle_cls) if battle_cls else Battle_State

    def run(self):
        b = self.bot
        self.warmup(["btn_route_confirm", "title_route"])

        while not b._stop:
            if self.heartbeat():
                return Init_State(b)

            scr, _ = b._grab()
            ok = (b._match_color(scr, "btn_route_confirm", b.thr_main) or
                  b._match_gray(scr, "btn_route_confirm", b.thr_main))
            if ok:
                b.click_abs(ok.center)
                time.sleep(b.sleep_fast * 1.2)
                return self.battle_cls(b)

            if b._match_gray(scr, "btn_battle_skip", b.thr_main):
                return self.battle_cls(b)
            if b._match_gray(scr, "title_relic", b.thr_tag):
                return Relic_Selection_State(b)

            time.sleep(b.sleep_fast)


class Battle_State(State_Base):
    NAME = "Battle"
    TIMEOUT_SECS = 45

    ROI_SKIP = (0.78, 0.00, 0.99, 0.22)
    ROI_NEXT = (0.72, 0.78, 0.99, 0.99)

    SPAM_SECS = 2.3
    SPAM_INTERVAL = 0.12
    SPAM_X_ANCHOR = 0.94
    SPAM_Y_ANCHORS = (0.10, 0.112, 0.113)

    # Post-relic chain to follow (normal battle: go back to route)
    POST_CHAIN = [Route_Selection_State]

    def run(self):
        b = self.bot
        self.warmup(["btn_battle_skip", "btn_skip", "btn_next"])
        t_enter = time.time()

        while not b._stop:
            if self.heartbeat():
                return Init_State(b)
            scr, _ = b._grab()

            nxt = (b._match_roi(scr, "btn_next", b.thr_main - 0.10, self.ROI_NEXT)
                   or b._match_gray(scr, "btn_next", b.thr_main - 0.08))
            if nxt:
                b.click_abs(nxt.center)
                time.sleep(b.sleep_fast)
                # Enter relic selection carrying the post-battle chain
                return Relic_Selection_State(b, after=list(self.POST_CHAIN))

            sk = (b._match_roi(scr, "btn_battle_skip", max(0.30, b.thr_skip_color - 0.08), self.ROI_SKIP, use_color=True)
                  or b._match_roi(scr, "btn_battle_skip", b.thr_main - 0.12, self.ROI_SKIP)
                  or b._match_roi(scr, "btn_skip", b.thr_main - 0.12, self.ROI_SKIP, use_color=True))
            if sk:
                b.click_abs(sk.center)
                time.sleep(0.05)
                b.click_abs(sk.center)
                time.sleep(b.sleep_fast * 0.8)
                continue

            if (time.time() - t_enter) < self.SPAM_SECS:
                bx = b._bbox
                x_rel = int(bx["width"] * self.SPAM_X_ANCHOR)
                for y_r in self.SPAM_Y_ANCHORS:
                    b.click_abs((x_rel, int(bx["height"] * y_r)))
                    time.sleep(0.04)
                time.sleep(self.SPAM_INTERVAL)
                continue

            time.sleep(b.sleep_base * 0.8)

class Boss_Battle_State(Battle_State):
    NAME = "Boss_Battle"
    # Note: assign POST_CHAIN after all classes are defined to avoid forward-reference errors
    POST_CHAIN: List[type[State_Base]] = []


class Relic_Selection_State(State_Base):
    NAME = "Relic_Select"
    TIMEOUT_SECS = 15
    DIAMOND_TPL = "relic_diamond"

    ROI_DIAMOND = (0.08, 0.18, 0.92, 0.58)
    CARD_CENTERS_REL = ((0.20, 0.62), (0.50, 0.62), (0.80, 0.62))

    def _abs_from_rel(self, rx: float, ry: float) -> tuple[int, int]:
        b = self.bot._bbox
        return (b["left"] + int(b["width"] * rx), b["top"] + int(b["height"] * ry))

    def run(self) -> "State_Base":
        b = self.bot
        self.warmup(["title_relic", self.DIAMOND_TPL, "title_route", "btn_battle_skip"])

        clicked = False
        t_clicked = 0.0
        t0 = time.time()

        while not b._stop and (time.time() - t0) < self.TIMEOUT_SECS:
            if self.heartbeat():
                b.log("[RELIC] watchdog -> Init")
                return Init_State(b)

            scr, _ = b._grab()

            # Seeing the route title means the relic page is finished (normal battle)
            if b._match_gray(scr, "title_route", b.thr_tag):
                return Route_Selection_State(b)
            # If Skip reappears we are back in battle
            if b._match_gray(scr, "btn_battle_skip", b.thr_main):
                return Battle_State(b)

            if clicked and (time.time() - t_clicked) < 0.6:
                time.sleep(b.sleep_fast)
                continue

            # 1) Prefer the card with the diamond marker
            hit_d = b._match_roi(scr, self.DIAMOND_TPL,
                                 max(b.thr_tag, 0.70), self.ROI_DIAMOND, use_color=True)
            if hit_d:
                b.log(f"[RELIC] diamond @ {hit_d.center} ({hit_d.maxv:.2f})")
                b.click_abs(hit_d.center)
                clicked = True
                t_clicked = time.time()
                time.sleep(b.sleep_fast)
                if self.after:
                    return self.next_from_chain()
                continue

            # 2) Otherwise click the leftmost card
            pt = self._abs_from_rel(*self.CARD_CENTERS_REL[0])
            b.log(f"[RELIC] click default left @ {pt}")
            b.click_abs(pt)
            clicked = True
            t_clicked = time.time()
            time.sleep(b.sleep_fast)
            if self.after:
                return self.next_from_chain()

        b.log("[RELIC] timeout -> Init")
        return Init_State(b)


class _BaseSkipBottomRight(State_Base):
    NAME = "SKIP"
    TIMEOUT_SECS = 10
    ROI_SKIP_BTN = (0.72, 0.82, 0.98, 0.98)  # Bottom-right button region

    def run(self) -> "State_Base":
        
        b = self.bot
        self.warmup(["btn_shop_skip", "btn_next"])
        t0 = time.time()
        while not b._stop and (time.time() - t0) < self.TIMEOUT_SECS:
            if self.heartbeat():
                return Init_State(b)
            scr, _ = b._grab()

            # If a clear Continue/Leave/Return after purchase button exists
            hit = (b._match_roi(scr, "btn_shop_skip", b.thr_main, self.ROI_SKIP_BTN, use_color=True)
                   or b._match_roi(scr, "btn_next", b.thr_main - 0.08, self.ROI_SKIP_BTN))
            if hit:
                b.click_abs(hit.center)
                time.sleep(b.sleep_fast * 1.1)
                return self.next_from_chain()

            # Fallback: click the ROI center once
            L, T, R, B = b._roi_abs(self.ROI_SKIP_BTN)
            b.click_abs(((L + R) // 2, (T + B) // 2))
            time.sleep(b.sleep_fast)
        return self.next_from_chain()  # Continue even on timeout

class Shop_State(_BaseSkipBottomRight):
    NAME = "Shop"

class Support_State(_BaseSkipBottomRight):
    NAME = "Support"


# ---- After all class definitions, fill in the boss post-battle chain to avoid forward-reference NameError ----
Boss_Battle_State.POST_CHAIN = [Shop_State, Support_State, Route_Selection_State]
