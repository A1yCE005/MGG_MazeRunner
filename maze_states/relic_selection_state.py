from __future__ import annotations

import time
from maze_core import State_Base

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
        from .init_state import Init_State
        from .route_selection_state import Route_Selection_State
        from .battle_state import Battle_State

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
