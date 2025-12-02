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

        self.current_target_animal = None   # (species_id, gender)


    def _get_my_cell(self) -> CellView:
        xcell, ycell = tuple(map(int, self.position))
        if not self.sight.cell_is_in_sight(xcell, ycell):
            raise Exception(f"{self} failed to find own cell")

        return self.sight.get_cellview_at(xcell, ycell)

    def _get_next_grid_target(self) -> tuple[float, float]:
        """Pick the next unvisited grid cell to explore"""
        # Try to find an unvisited cell
        # NOTE: can tune later this was arbitrarily picked for now
        attempts = 0
        max_attempts = 100

        while attempts < max_attempts:
            grid_x = randint(0, 9)
            grid_y = randint(0, 9)

            # Avoid visited cells + same cell we are already moving toward
            if (grid_x, grid_y) in self.visited_cells or (
                grid_x,
                grid_y,
            ) == self.current_target_cell:
                attempts += 1
                continue

            # Valid new target
            self.visited_cells.add((grid_x, grid_y))
            self.current_target_cell = (grid_x, grid_y)
            return self._get_grid_center(grid_x, grid_y)

        # If most cells are visited then it's fine and we'll reset to allow revists
        self.visited_cells.clear()
        grid_x = randint(0, 9)
        grid_y = randint(0, 9)
        self.visited_cells.add((grid_x, grid_y))
        self.current_target_cell = (grid_x, grid_y)
        return self._get_grid_center(grid_x, grid_y)

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
                    dx = xrandom**3
                else:
                    dx = 1 - (1 - xrandom) ** 3
                dx = int(999 * dx)
                dy = int(999 * random.random())
            else:
                yrandom = random.random()
                if yrandom < 0.5:
                    dy = yrandom**3
                else:
                    dy = 1 - (1 - yrandom) ** 3
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

        # Broadcast what animal helper is targeting (species,gender) or 0 if none
        if self.current_target_animal is not None:
            species_id, gender_enum = self.current_target_animal
            # Convert enum -> integer 0/1/2
            if gender_enum == Gender.Male:
                gender = 0
            elif gender_enum == Gender.Female:
                gender = 1
            else:
                gender = 2
            msg = (species_id << 2) | gender  # up to ~10 bits safe
        else:
            msg = 0

        if not self.is_message_valid(msg):
            msg = msg & 0xFF

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
    
    def _get_complement_gender(self, gender: Gender) -> Gender:
        """ Prioritize opposite gender of animals that helpers currently have """
        if gender == Gender.Male:
            return Gender.Female
        return Gender.Male
    
    def _decode_target_message(self, msg_value: int):
        """
        Returns (species_id, gender) or None.
        Message format: (species_id << 2) | gender
        """
        if msg_value == 0:
            return None
        species_id = msg_value >> 2
        gender = msg_value & 0b11
        return (species_id, gender)

    
    def _find_best_animal(self, targets_taken: set[tuple[int,int]]) -> tuple[int,int] | None:
        """
        Returns location of the best animal:
        1. Prefer complementary gender to what we already have in flock.
        2. Avoid animals already targeted by other helpers.
        3. Otherwise fall back to any useful animal.
        """
        # Determine which species/genders we already carry
        species_in_flock = {a.species_id: a.gender for a in self.flock}

        preferred_candidates = []
        fallback_candidates = []

        for cellview in self.sight:
            for animal in cellview.animals:
                key = (animal.species_id, animal.gender)

                # Skip animals already targeted by other helpers
                if key in targets_taken:
                    continue

                # Skip animals where their species is complete
                if animal.species_id in self.complete_species:
                    continue

                # Skip animals already known to be in the ark
                if key in self.internal_ark:
                    continue

                if key in self.flock_id:  
                    continue

                dist = distance(*self.position, cellview.x, cellview.y)

                # Prioritize pairs: let's go get the opposite gender of what we already have
                if animal.species_id in species_in_flock:
                    desired_gender = self._get_complement_gender(species_in_flock[animal.species_id])
                    if desired_gender == animal.gender:
                        preferred_candidates.append((dist, (cellview.x, cellview.y)))
                        continue

                # Fallback: get any useful animal
                fallback_candidates.append((dist, (cellview.x, cellview.y)))

        # Prefer complementary gender
        if preferred_candidates:
            return min(preferred_candidates, key=lambda x: x[0])[1]

        if fallback_candidates:
            return min(fallback_candidates, key=lambda x: x[0])[1]

        return None

    def get_action(self, messages: list[Message]) -> Action | None:
        targets_taken = set()

        for msg in messages:
            decoded = self._decode_target_message(msg.contents)
            if decoded is not None:
                targets_taken.add(decoded)

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
        print(potential_animals)

        # If cell has animals but we cannot pick any -> move away
        #if len(cellview.animals) > 0 and len(potential_animals) == 0:
        #    self.mode = "move_away"
        #    self.countdown = 10
        #    return Move(*self.move_towards(*self.direction))

        if len(potential_animals) > 0 and self.is_minHelper(cellview):
            print("a")
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
            print("there")
            return Move(*self.move_towards(*self.direction))
        print("else")
        """If I see any animals that might not be in the arc, I'll chase the 
        closest one"""
        #closest_animal = self._find_closest_animal()
        #if closest_animal:
            # This means the random_player will even approach
            # animals in other helpers' flocks
        #    return Move(*self.move_towards(*closest_animal))

        best_pos = self._find_best_animal(targets_taken)

        if best_pos is not None:
            # Identify which animal at that location is the one we actually want
            # (species_id, gender) so we can broadcast it.
            best_species = None
            best_gender = None
            for cell in self.sight:
                if (cell.x, cell.y) == best_pos:
                    # Pick the first matching animal
                    for animal in cell.animals:
                        tup = (animal.species_id, animal.gender)
                        if tup not in targets_taken and \
                        tup not in self.internal_ark and \
                        animal.species_id not in self.complete_species:
                            best_species = animal.species_id
                            best_gender = animal.gender
                            break
                    break

            # Record and transmit
            if best_species is not None:
                self.current_target_animal = (best_species, best_gender)

            return Move(*self.move_towards(*best_pos))
        else:
            self.current_target_animal = None


        # Systematic grid exploration
        if self.mode == "waiting":
            # Pick a new grid cell to explore
            direction = self._get_next_grid_target()
            self.mode = "moving"
            self.direction = direction
            return Move(*self.move_towards(*self.direction))
        else:
            # Check if we've reached our target grid cell
            if self.current_target_cell:
                current_grid = self._get_grid_cell(*self.position)
                if current_grid == self.current_target_cell:
                    # Reached target, pick new cell
                    direction = self._get_next_grid_target()
                    self.mode = "moving"
                    self.direction = direction
                    return Move(*self.move_towards(*self.direction))

            # Check if close to direction target
            if distance(*self.position, *self.direction) < 10:
                # Pick new grid cell
                direction = self._get_next_grid_target()
                self.mode = "moving"
                self.direction = direction
                return Move(*self.move_towards(*self.direction))
            else:
                # Keep moving toward current target
                return Move(*self.move_towards(*self.direction))
