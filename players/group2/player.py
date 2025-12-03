from random import choice, randint
import random

from core.action import Action, Move, Obtain
from core.message import Message
from core.player import Player
from core.snapshots import HelperSurroundingsSnapshot
from core.views.player_view import Kind
from core.views.cell_view import CellView
from core.animal import Gender


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
        # print(f"I am {self}")

        self.is_raining = False
        self.hellos_received = []
        self.mode = "waiting"
        # spread out initial direction outward from ark
        self.direction = (ark_x + randint(-300, 300), ark_y + randint(-300, 300))

        self.internal_ark = set()
        self.complete_species = set()
        self.flock_id = set()

        self.countdown = 0
        self.rain = False
        self.timer = 1008

        self.recent_positions = []  # Track last 50 positions
        self.max_history = 50

        # Grid-based exploration
        # Scale down grid map into 100x100 cells (10x10 grid)
        self.grid_size = 100
        self.visited_cells = set()
        self.current_target_cell = None

        # Setup for helpers to broadcast their target cell
        # helper_id -> (grid_x, grid_y)
        self.claimed_cells_by_helpers = {}
        self.my_grid = (0, 0)

    def _get_my_cell(self) -> CellView:
        xcell, ycell = tuple(map(int, self.position))
        if not self.sight.cell_is_in_sight(xcell, ycell):
            raise Exception(f"{self} failed to find own cell")

        return self.sight.get_cellview_at(xcell, ycell)

    def _get_next_grid_target(self) -> tuple[float, float]:
        """Pick the next unclaimed grid cell by another helper to explore"""

        claimed = set(self.claimed_cells_by_helpers.values())

        # Tune later: try up to 200 attempts to find an unused cell
        for _ in range(200):
            grid_x = randint(0, 9)
            grid_y = randint(0, 9)

            # Avoid cells visited or claimed or already target
            if (grid_x, grid_y) in claimed:
                continue
            if (grid_x, grid_y) == self.current_target_cell:
                continue
            if (grid_x, grid_y) in self.visited_cells:
                continue

            self.visited_cells.add((grid_x, grid_y))
            self.current_target_cell = (grid_x, grid_y)
            result = self._get_grid_center(grid_x, grid_y)
            if (
                distance(
                    result[0], result[1], self.ark_position[0], self.ark_position[1]
                )
                > 999
            ):
                continue
            return result

        # If grid is fully used fallback randomly
        while True:
            grid_x = randint(0, 9)
            grid_y = randint(0, 9)
            self.visited_cells.add((grid_x, grid_y))
            self.current_target_cell = (grid_x, grid_y)
            result = self._get_grid_center(grid_x, grid_y)
            if (
                distance(
                    result[0], result[1], self.ark_position[0], self.ark_position[1]
                )
                > 999
            ):
                continue
            return result

    def _get_grid_cell(self, x: float, y: float) -> tuple[int, int]:
        """Convert a position to the scaled down 10x10 grid cell coordinates"""
        grid_x = max(0, min(9, int(x // self.grid_size)))
        grid_y = max(0, min(9, int(y // self.grid_size)))
        return (grid_x, grid_y)

    def _get_grid_center(self, grid_x: int, grid_y: int) -> tuple[float, float]:
        """Get the center point of the scaled down 10x10 grid cell"""
        center_x = grid_x * self.grid_size + self.grid_size // 2
        center_y = grid_y * self.grid_size + self.grid_size // 2
        return (center_x, center_y)

    def animal_to_tuple(self, animal):
        s_id = animal.species_id
        if animal.gender == Gender.Male:
            g = 0
        elif animal.gender == Gender.Female:
            g = 1
        else:
            g = 2
        return (s_id, g)

    def _find_closest_animal(self) -> tuple[int, int] | None:
        closest_animal = None
        closest_dist = -1
        closest_pos = None
        for cellview in self.sight:
            if len(cellview.animals) > 0 and len(cellview.helpers) == 0:
                for animal in cellview.animals:
                    dist = distance(*self.position, cellview.x, cellview.y)
                    if (
                        (animal.species_id, animal.gender) not in self.internal_ark
                        and animal.species_id not in self.complete_species
                    ):
                        if closest_animal is None:
                            closest_animal = animal
                            closest_dist = dist
                            closest_pos = (cellview.x, cellview.y)
                        elif dist < closest_dist:
                            closest_animal = choice(tuple(cellview.animals))
                            closest_dist = dist
                            closest_pos = (cellview.x, cellview.y)

        return closest_pos

    def _get_random_location(self) -> tuple[float, float]:
        old_x, old_y = self.position
        while True:
            orientation = random.random()
            if orientation < 0.5:
                xrandom = random.random()
                if xrandom < 0.5:
                    dx = xrandom**2
                else:
                    dx = 1 - (1 - xrandom) ** 2
                dx = int(999 * dx)
                dy = int(999 * random.random())
            else:
                yrandom = random.random()
                if yrandom < 0.5:
                    dy = yrandom**2
                else:
                    dy = 1 - (1 - yrandom) ** 2
                dy = int(999 * dy)
                dx = int(999 * random.random())
            if distance(dx, dy, self.ark_position[0], self.ark_position[1]) < 1000:
                break

        return dx, dy

    def check_surroundings(self, snapshot: HelperSurroundingsSnapshot) -> int:
        # I can't trust that my internal position and flock matches the simulators
        # For example, I wanted to move in a way that I couldn't
        # or the animal I wanted to obtain was actually obtained by another helper
        self.position = snapshot.position
        self.flock = snapshot.flock

        self.sight = snapshot.sight
        self.is_raining = snapshot.is_raining

        # Mark current grid cell(the scaled down 10x10 one that hosts 10 cells) as visited when exploring
        if self.is_flock_empty():
            current_grid = self._get_grid_cell(*self.position)
            self.visited_cells.add(current_grid)

        # Track when we're exploring (not when returning to ark with animals)
        if self.is_flock_empty() or len(self.recent_positions) == 0:
            self.recent_positions.append(self.position)
            # Keep only the most recent positions
            if len(self.recent_positions) > self.max_history:
                self.recent_positions.pop(0)

        # Clear some history when at ark to allow fresh exploration cycles(last 20 for now)
        if snapshot.ark_view is not None and self.is_flock_empty():
            # NOTE: tune later
            if len(self.recent_positions) > 20:
                self.recent_positions = self.recent_positions[-20:]

        """Update internal arc information"""
        if snapshot.ark_view is not None:
            arc_animals = set()
            for animal in snapshot.ark_view.animals:
                arc_animals.add(self.animal_to_tuple(animal))
            self.internal_ark = arc_animals
            for tuple in arc_animals:
                s_id = tuple[0]
                if (s_id, 0) in arc_animals and (s_id, 1) in arc_animals:
                    self.complete_species.add(s_id)

        # print(snapshot.flock)
        self.flock_id = set()
        for animal in snapshot.flock:
            self.flock_id.add(self.animal_to_tuple(animal))

        # print(self.flock_id)

        # Broadcast my current grid cell ---
        gx, gy = self._get_grid_cell(*self.position)
        self.my_grid = (gx, gy)
        msg = self._encode_grid_cell(gx, gy)

        if not self.is_message_valid(msg):
            msg &= 0xFF

        return msg

    def potential_animals(self, cellview_animals):
        result = set()
        for animal in cellview_animals:
            if self.animal_to_tuple(animal) not in self.flock_id:
                result.add(animal)
        return result

    def duplicate_animal_spotted(self, cellview):
        animal_set = set()
        for animal in cellview.animals:
            if self.animal_to_tuple(animal) in animal_set:
                return True
            animal_set.add(self.animal_to_tuple(animal))
        return False

    def is_minHelper(self, cellview):
        for helper in cellview.helpers:
            if helper.id < self.id:
                return False
        return True

    def _score_animal(self, animal, current_dist: float) -> float:
        score = 100.0  # Base score
        n_i = self.species_populations.get(animal.species_id, 1000)

        # Rarity bonus
        score += 10000.0 / n_i

        # Ark completeness bonus
        if animal.species_id not in self.complete_species:
            score += 50.0

        # Flock complementarity bonus
        needed_gender = Gender.Female if animal.gender == Gender.Male else Gender.Male
        needed_gender_int = 1 if needed_gender == Gender.Female else 0
        # Big reward if this completes a pair
        if (animal.species_id, needed_gender_int) in self.flock_id:
            score += 500.0

        # Distance penalty
        final_score = score / max(1.0, current_dist)

        return final_score

    def _find_best_scoring_animal(self):
        """Return (x,y) of the best-scoring animal in sight."""
        best_score = -1.0
        best_position = None

        for cell in self.sight:
            if len(cell.animals) == 0:
                continue

            # Skip animals being handled by another helper
            if len(cell.helpers) > 0:
                continue

            cx, cy = cell.x, cell.y

            for animal in cell.animals:
                # Skip animals already in ark or already completed
                if self.animal_to_tuple(animal) in self.internal_ark:
                    continue
                if animal.species_id in self.complete_species:
                    continue

                dist = distance(self.position[0], self.position[1], cx, cy)
                score = self._score_animal(animal, dist)

                if score > best_score:
                    best_score = score
                    best_position = (cx, cy)

        return best_position

    def _encode_grid_cell(self, gx, gy):
        """Encode a 10x10 grid cell into a single byte."""
        # Store grid x in upper 4 bits, grid y in lower 4
        return (gx << 4) | gy

    def _decode_grid_cell(self, byte):
        """Decode the helper's broadcast message."""
        # gx was originally shifted left by 4 so reverse
        gx = (byte >> 4) & 0x0F
        gy = byte & 0x0F
        return gx, gy

    def get_action(self, messages: list[Message]) -> Action | None:
        for msg in messages:
            gx, gy = self._decode_grid_cell(msg.contents)
            self.claimed_cells_by_helpers[msg.from_helper.id] = (gx, gy)

        # noah shouldn't do anything
        if self.kind == Kind.Noah:
            return None

        # Get your ass back to the ark now
        if self.mode == "get_back":
            return Move(*self.move_towards(*self.ark_position))

        """If it's raining, keep searching. However, if you are too close to 
        the deadline, set mode to get_back to immediatly travel to the arc"""
        if self.rain:
            self.timer -= 1
            if (
                self.timer
                - distance(
                    self.position[0],
                    self.position[1],
                    self.ark_position[0],
                    self.ark_position[1],
                )
                <= 20
            ):
                self.mode = "get_back"
                return Move(*self.move_towards(*self.ark_position))

        if self.is_raining and not self.rain:
            self.rain = True

        # If I have obtained an animal, go to ark
        if len(self.flock) == 4:
            # Now heading to ark
            self.direction = self.ark_position
            return Move(*self.move_towards(*self.ark_position))

        """If a helper checked and animal and noted it is already in the arc
        we use this function to force a 10 move walk"""
        if self.mode == "move_away":
            if self.countdown <= 0:
                self.mode = "moving"
            else:
                self.countdown -= 1
                return Move(*self.move_towards(*self.direction))

        # If I've reached an animal, I'll obtain it
        cellview = self._get_my_cell()

        if self.duplicate_animal_spotted(cellview):
            self.mode = "move_away"
            self.countdown = 10
            return Move(*self.move_towards(*self.direction))

        potential_animals = self.potential_animals(cellview.animals)
        # print(potential_animals)
        if len(potential_animals) > 0 and self.is_minHelper(cellview):
            # print("a")
            for animal in cellview.animals:
                if (
                    self.animal_to_tuple(animal) not in self.internal_ark
                    and animal.species_id not in self.complete_species
                    and self.animal_to_tuple(animal) not in self.flock_id
                ):
                    return Obtain(animal)
            # direction = self._get_random_location()
            self.mode = "move_away"
            # self.direction = direction
            self.countdown = 10
            # print("there")
            return Move(*self.move_towards(*self.direction))
        # print("else")
        """If I see any animals that might not be in the arc, I'll chase the 
        closest one"""
        # closest_animal = self._find_closest_animal()
        # if closest_animal:
        # This means the random_player will even approach
        # animals in other helpers' flocks
        #    return Move(*self.move_towards(*closest_animal))
        best_animal_pos = self._find_best_scoring_animal()
        if best_animal_pos is not None:
            return Move(*self.move_towards(*best_animal_pos))

        # Systematic grid exploration
        """Starting from here is the code using self._get_random_location, 
        the one that takes random values and prioretizes edges. """
        if self.mode == "waiting":
            # Pick a new grid cell to explore
            direction = self._get_random_location()
            self.mode = "moving"
            self.direction = direction
            return Move(*self.move_towards(*self.direction))
        else:
            # Check if we've reached our target grid cell
            if self.position == self.direction:
                # Reached target, pick new cell
                direction = self._get_random_location()
                self.mode = "moving"
                self.direction = direction
                return Move(*self.move_towards(*self.direction))

            # Check if close to direction target
            if distance(*self.position, *self.direction) < 10:
                # Pick new grid cell
                direction = self._get_random_location()
                self.mode = "moving"
                self.direction = direction
                return Move(*self.move_towards(*self.direction))
            else:
                # Keep moving toward current target
                return Move(*self.move_towards(*self.direction))

        """Starting from here is the code using self._get_next_grid_target, 
        It's slightly different from self._get_random_location."""
        # if self.mode == "waiting":
        #     # Pick a new grid cell to explore
        #     direction = self._get_next_grid_target()
        #     self.mode = "moving"
        #     self.direction = direction
        #     return Move(*self.move_towards(*self.direction))
        # else:
        #     # Check if we've reached our target grid cell
        #     if self.current_target_cell:
        #         current_grid = self._get_grid_cell(*self.position)
        #         if current_grid == self.current_target_cell:
        #             # Reached target, pick new cell
        #             direction = self._get_next_grid_target()
        #             self.mode = "moving"
        #             self.direction = direction
        #             return Move(*self.move_towards(*self.direction))

        #     # Check if close to direction target
        #     if distance(*self.position, *self.direction) < 10:
        #         # Pick new grid cell
        #         direction = self._get_next_grid_target()
        #         self.mode = "moving"
        #         self.direction = direction
        #         return Move(*self.move_towards(*self.direction))
        #     else:
        #         # Keep moving toward current target
        #         return Move(*self.move_towards(*self.direction))
