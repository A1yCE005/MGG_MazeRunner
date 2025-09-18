from __future__ import annotations

import time
from maze_core import State_Base

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
        from .init_state import Init_State
        from .relic_selection_state import Relic_Selection_State
        from .route_confirmation_state import Route_Confirmation_State
        from .battle_state import Battle_State
        from .boss_battle_state import Boss_Battle_State

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

        return None
