from __future__ import annotations

import time
from maze_core import State_Base

class Route_Confirmation_State(State_Base):
    NAME = "Route_Confirm"
    TIMEOUT_SECS = 10

    def __init__(self, bot: "MazeBot", after: list[type["State_Base"]] | None = None,
                 battle_cls: type[State_Base] | None = None):
        super().__init__(bot, after)
        # Fix: default cannot forward reference undefined class in signature
        from .battle_state import Battle_State
        from typing import cast

        self.battle_cls = cast(type[State_Base], battle_cls) if battle_cls else Battle_State

    def run(self):
        from .init_state import Init_State
        from .relic_selection_state import Relic_Selection_State

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

        return None
