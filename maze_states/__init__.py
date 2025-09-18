from .init_state import Init_State
from .prepare_state import Prepare_State
from .route_selection_state import Route_Selection_State
from .route_confirmation_state import Route_Confirmation_State
from .battle_state import Battle_State
from .boss_battle_state import Boss_Battle_State
from .relic_selection_state import Relic_Selection_State
from .base_skip_bottom_right import _BaseSkipBottomRight
from .shop_state import Shop_State
from .support_state import Support_State

Battle_State.POST_CHAIN = [Route_Selection_State]
Boss_Battle_State.POST_CHAIN = [Shop_State, Support_State, Route_Selection_State]

__all__ = [
    "Init_State",
    "Prepare_State",
    "Route_Selection_State",
    "Route_Confirmation_State",
    "Battle_State",
    "Boss_Battle_State",
    "Relic_Selection_State",
    "_BaseSkipBottomRight",
    "Shop_State",
    "Support_State",
]
