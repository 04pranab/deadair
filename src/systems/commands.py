"""Per-player input for one simulation step. The sim consumes only these, never raw devices,
so local keyboards, gamepads, bots, tests and (later) network clients are interchangeable."""
from dataclasses import dataclass


@dataclass
class InputFrame:
    mx: float = 0.0
    my: float = 0.0
    aim_x: float = 0.0          # optional explicit aim (right stick); (0,0) means "use movement"
    aim_y: float = 0.0
    fire: bool = False
    dodge: bool = False         # pressed this step
    ability: bool = False       # pressed this step
    interact: bool = False      # pressed this step
    interact_held: bool = False

    def merged(self, other):
        """Combine two frames when several fixed steps share one rendered frame (edge flags stick)."""
        return InputFrame(other.mx, other.my, other.aim_x, other.aim_y, other.fire,
                          self.dodge or other.dodge, self.ability or other.ability,
                          self.interact or other.interact, other.interact_held)
