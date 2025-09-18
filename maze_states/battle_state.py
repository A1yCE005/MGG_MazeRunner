from __future__ import annotations

import time
from typing import List

from maze_core import State_Base

class Battle_State(State_Base):
    NAME = "Battle"
    TIMEOUT_SECS = 45

    ROI_SKIP = (0.78, 0.00, 0.99, 0.22)
    ROI_NEXT = (0.72, 0.78, 0.99, 0.99)

    SPAM_SECS = 2.3
    SPAM_INTERVAL = 0.12
    SPAM_X_ANCHOR = 0.94
    SPAM_Y_ANCHORS = (0.10, 0.112, 0.113)

    POST_CHAIN: List[type[State_Base]] = []

    def run(self):
        from .init_state import Init_State
        from .relic_selection_state import Relic_Selection_State

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

        return None
