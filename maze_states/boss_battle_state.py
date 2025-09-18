from __future__ import annotations

from typing import List

from maze_core import State_Base
from .battle_state import Battle_State

class Boss_Battle_State(Battle_State):
    NAME = "Boss_Battle"
    POST_CHAIN: List[type[State_Base]] = []
