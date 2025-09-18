from __future__ import annotations

import time
from maze_core import State_Base

class Prepare_State(State_Base):
    NAME = "Prepare"
    TIMEOUT_SECS = 15

    def run(self):
        from .route_selection_state import Route_Selection_State

        b = self.bot
        self.warmup(["btn_explore", "btn_explore_confirm", "tag_select"])

        clicked_explore = False
        while not b._stop:
            if self.heartbeat():
                from .init_state import Init_State
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
