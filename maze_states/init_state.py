from __future__ import annotations

import time
from maze_core import State_Base

class Init_State(State_Base):
    NAME = "Init"
    TIMEOUT_SECS = 15

    def run(self):
        from .prepare_state import Prepare_State
        from .route_selection_state import Route_Selection_State
        from .route_confirmation_state import Route_Confirmation_State
        from .battle_state import Battle_State
        from .relic_selection_state import Relic_Selection_State

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
                return Relic_Selection_State(b)

            time.sleep(b.sleep_fast)
        return None
