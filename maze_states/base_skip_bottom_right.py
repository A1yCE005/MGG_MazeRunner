from __future__ import annotations

import time
from maze_core import State_Base

class _BaseSkipBottomRight(State_Base):
    NAME = "SKIP"
    TIMEOUT_SECS = 10
    ROI_SKIP_BTN = (0.72, 0.82, 0.98, 0.98)  # Bottom-right button region

    def run(self) -> "State_Base":
        from .init_state import Init_State

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
