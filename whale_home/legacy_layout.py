"""Frozen grid validation for legacy imports; never used by the fixed scene."""

from __future__ import annotations

from pathfinding.core.diagonal_movement import DiagonalMovement
from pathfinding.core.grid import Grid
from pathfinding.finder.a_star import AStarFinder

from .errors import HomeError
from .legacy_v1 import (
    GRID_HEIGHT,
    GRID_WIDTH,
    HomeState,
    ItemDefinition,
    ItemInstance,
    Position,
)


def definitions_by_id(state: HomeState) -> dict[str, ItemDefinition]:
    return {definition.id: definition for definition in state.definitions}


def occupied(instance: ItemInstance, definition: ItemDefinition) -> set[tuple[int, int]]:
    if instance.position is None:
        return set()
    return {
        (instance.position.x + dx, instance.position.y + dy)
        for dx in range(definition.width)
        for dy in range(definition.height)
    }


def walk_matrix(state: HomeState) -> list[list[int]]:
    matrix = [[1] * GRID_WIDTH for _ in range(GRID_HEIGHT)]
    definitions = definitions_by_id(state)
    for instance in state.instances:
        definition = definitions[instance.definition_id]
        if definition.blocks_movement:
            for x, y in occupied(instance, definition):
                if 0 <= x < GRID_WIDTH and 0 <= y < GRID_HEIGHT:
                    matrix[y][x] = 0
    return matrix


def find_path(matrix: list[list[int]], start: Position, end: Position) -> list[Position]:
    if not matrix[end.y][end.x] or not matrix[start.y][start.x]:
        return []
    grid = Grid(matrix=matrix)
    finder = AStarFinder(diagonal_movement=DiagonalMovement.never)
    path, _ = finder.find_path(grid.node(start.x, start.y), grid.node(end.x, end.y), grid)
    return [Position(x=node.x, y=node.y) for node in path]


def path_to_item(state: HomeState, instance: ItemInstance) -> list[Position]:
    if instance.position is None:
        raise HomeError("先把这件物品放进房间吧。")
    definition = definitions_by_id(state)[instance.definition_id]
    cells = occupied(instance, definition)
    candidates: set[tuple[int, int]] = set()
    if not definition.blocks_movement:
        candidates.update(cells)
    for x, y in cells:
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            point = (x + dx, y + dy)
            if point not in cells and 0 <= point[0] < GRID_WIDTH and 0 <= point[1] < GRID_HEIGHT:
                candidates.add(point)
    matrix = walk_matrix(state)
    paths = [
        path
        for x, y in sorted(candidates)
        if (path := find_path(matrix, state.character.position, Position(x=x, y=y)))
    ]
    if not paths:
        raise HomeError("这里走不过去，给她留一条通道吧。")
    return min(paths, key=len)


def validate_layout(state: HomeState) -> None:
    definitions = definitions_by_id(state)
    occupied_cells: set[tuple[int, int]] = set()
    for instance in state.instances:
        definition = definitions[instance.definition_id]
        cells = occupied(instance, definition)
        if any(x >= GRID_WIDTH or y >= GRID_HEIGHT for x, y in cells):
            raise HomeError("物品不能放到房间外。")
        if definition.blocks_movement:
            if cells & occupied_cells:
                raise HomeError("两件物品挤在一起了，换个位置吧。")
            occupied_cells.update(cells)
    character_cell = (state.character.position.x, state.character.position.y)
    if character_cell in occupied_cells:
        raise HomeError("这里是鲸鱼娘正在站的位置。")
    for instance in state.instances:
        if instance.position is not None:
            path_to_item(state, instance)
