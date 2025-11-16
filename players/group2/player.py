from random import random, choice

from core.action import Action, Move, Obtain
from core.message import Message
from core.player import Player
from core.snapshots import HelperSurroundingsSnapshot
from core.views.player_view import Kind
from core.views.cell_view import CellView


def distance(x1: float, y1: float, x2: float, y2: float) -> float:
    return (abs(x1 - x2) ** 2 + abs(y1 - y2) ** 2) ** 0.5


class Player2(Player):
    def __init__(
        self,
        id: int,
        ark_x: int,
        ark_y: int,
        kind: Kind,
        num_helpers: int,
        species_populations: dict[str, int],
    ):
        super().__init__(id, ark_x, ark_y, kind, num_helpers, species_populations)
        #print(f"I am {self}")

        self.is_raining = False
        self.hellos_received = []

        self.assigned_region = None
        self.target_position = None
        
        # Have helpers be assigned regions to explore based on area
        if self.kind == Kind.Helper:
            self.assigned_region = self._assign_region(id, num_helpers, ark_x, ark_y)
            self.target_position = self._get_region_center(self.assigned_region)

    def _assign_region(self, helper_id: int, num_helpers: int, ark_x: int, ark_y: int) -> dict:
        """ Assigns helpers to different regions based on the area of each region """
        # for now examine it only in terms of the 4 quadrants
        quadrants = [
            {"name": "NE", "x_range": (ark_x, 1000), "y_range": (ark_y, 1000)},
            {"name": "NW", "x_range": (0, ark_x), "y_range": (ark_y, 1000)},
            {"name": "SE", "x_range": (ark_x, 1000), "y_range": (0, ark_y)},
            {"name": "SW", "x_range": (0, ark_x), "y_range": (0, ark_y)},
        ]

        # Calculate area of each quadrant surrounding the ark
        for q in quadrants:
            width = q["x_range"][1] - q["x_range"][0]
            height = q["y_range"][1] - q["y_range"][0]
            q["area"] = width * height
        
        total_area = sum(q["area"] for q in quadrants)

        # Assign helpers proportionally to areas = helpers * quadrant area / total area
        helpers_assigned = 0
        for q in quadrants:
            q["helper_count"] = int(num_helpers * q["area"] / total_area)
            helpers_assigned += q["helper_count"]
        
        # FIX: distribute remaining helpers(due to int rounding for helper count) to largest quadrants
        remaining = num_helpers - helpers_assigned
        quadrants_sorted = sorted(quadrants, key=lambda q: q["area"], reverse=True)
        for i in range(remaining):
            # add 1 helper to the largest quadrants
            quadrants_sorted[i]["helper_count"] += 1

        # walk through helper slots until we find where the id falls
        helper_count = 0
        for q in quadrants:
            # check if helper_id in quadrant: how many helper slots we've passed so far + num helpers that belong in this quadrant
            if helper_id < helper_count + q["helper_count"]:
                return q
            helper_count += q["helper_count"]
        
        # fallback but shouldn't happen anymore?
        return quadrants[0]
    
    def _get_region_center(self, region: dict) -> tuple[float, float]:
        """Get the center point of the assigned region"""
        x_min, x_max = region["x_range"]
        y_min, y_max = region["y_range"]
        return ((x_min + x_max) / 2, (y_min + y_max) / 2)
    
    def _find_closest_animal_in_region(self) -> tuple[int, int] | None:
        """Find the closest animal within a helper's assigned region"""
        closest_pos = None
        closest_dist = float('inf')
        
        for cellview in self.sight:
            if len(cellview.animals) > 0 and self._is_in_my_region(cellview.x, cellview.y):
                dist = distance(self.position[0], self.position[1], cellview.x, cellview.y)
                if dist < closest_dist:
                    closest_dist = dist
                    closest_pos = (cellview.x, cellview.y)
        
        return closest_pos
    
    def _is_in_my_region(self, x: float, y: float) -> bool:
        """Check if a position is withinthe helper's assigned region"""
        if self.assigned_region is None:
            return True
        
        x_min, x_max = self.assigned_region["x_range"]
        y_min, y_max = self.assigned_region["y_range"]
        return x_min <= x < x_max and y_min <= y < y_max
    
    def _move_towards_target(self) -> tuple[float, float]:
        """Move towards the target position in the assigned region."""
        if self.target_position is None:
            self.target_position = self._get_region_center(self.assigned_region)
        
        return self.move_towards(*self.target_position)

    def _get_my_cell(self) -> CellView:
        xcell, ycell = tuple(map(int, self.position))
        if not self.sight.cell_is_in_sight(xcell, ycell):
            raise Exception(f"{self} failed to find own cell")

        return self.sight.get_cellview_at(xcell, ycell)

    def _find_closest_animal(self) -> tuple[int, int] | None:
        closest_animal = None
        closest_dist = -1
        closest_pos = None
        for cellview in self.sight:
            if len(cellview.animals) > 0:
                dist = distance(*self.position, cellview.x, cellview.y)
                if closest_animal is None or dist < closest_dist:
                    closest_animal = choice(tuple(cellview.animals))
                    closest_dist = dist
                    closest_pos = (cellview.x, cellview.y)

        return closest_pos

    def _get_random_move(self) -> tuple[float, float]:
        old_x, old_y = self.position
        dx, dy = random() - 0.5, random() - 0.5

        while not (self.can_move_to(old_x + dx, old_y + dy)):
            dx, dy = random() - 0.5, random() - 0.5

        return old_x + dx, old_y + dy

    def check_surroundings(self, snapshot: HelperSurroundingsSnapshot) -> int:
        # I can't trust that my internal position and flock matches the simulators
        # For example, I wanted to move in a way that I couldn't
        # or the animal I wanted to obtain was actually obtained by another helper
        self.position = snapshot.position
        self.flock = snapshot.flock

        self.sight = snapshot.sight
        self.is_raining = snapshot.is_raining

        # if I didn't receive any messages, broadcast "hello"
        # a "hello" message is when a player's id bit is set
        if len(self.hellos_received) == 0:
            msg = 1 << (self.id % 8)
        else:
            # else, acknowledge all "hello"'s I got last turn
            # do this with a bitwise OR of all IDs I got
            msg = 0
            for hello in self.hellos_received:
                msg |= hello
            self.hellos_received = []

        if not self.is_message_valid(msg):
            msg = msg & 0xFF

        return msg

    def get_action(self, messages: list[Message]) -> Action | None:
        for msg in messages:
            if 1 << (msg.from_helper.id % 8) == msg.contents:
                self.hellos_received.append(msg.contents)

        # noah shouldn't do anything
        if self.kind == Kind.Noah:
            return None

        # If it's raining, go to ark
        if self.is_raining:
            return Move(*self.move_towards(*self.ark_position))

        # If I have obtained an animal, go to ark
        if not self.is_flock_empty():
            return Move(*self.move_towards(*self.ark_position))

        # If I've reached an animal, I'll obtain it
        cellview = self._get_my_cell()
        if len(cellview.animals) > 0:
            # This means the random_player will even attempt to
            # (unsuccessfully) obtain animals in other helpers' flocks
            random_animal = choice(tuple(cellview.animals))
            return Obtain(random_animal)

        # If I see any animals, I'll chase the closest one
        closest_animal = self._find_closest_animal_in_region()
        if closest_animal:
            # This means the random_player will even approach
            # animals in other helpers' flocks
            return Move(*self.move_towards(*closest_animal))
        
        # Explore assigned region
        if self.assigned_region:
            return Move(*self._move_towards_target())

        # Last case(shouldn't happen anymore): Move in a random direction
        return Move(*self._get_random_move())
