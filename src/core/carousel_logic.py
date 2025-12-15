"""Carousel business logic - platform agnostic."""

from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass
class CarouselState(Generic[T]):
    """State for a carousel/paginated view."""

    items: list[T]
    current_index: int = 0
    page_size: int = 1

    @property
    def total_items(self) -> int:
        return len(self.items)

    @property
    def current_item(self) -> T | None:
        if 0 <= self.current_index < len(self.items):
            return self.items[self.current_index]
        return None

    @property
    def has_next(self) -> bool:
        return self.current_index < len(self.items) - 1

    @property
    def has_prev(self) -> bool:
        return self.current_index > 0


class CarouselController(Generic[T]):
    """Controls carousel navigation and selection."""

    def next_page(self, state: CarouselState[T]) -> CarouselState[T]:
        """Move to next item, returns new state."""
        if state.has_next:
            return CarouselState(
                items=state.items,
                current_index=state.current_index + 1,
                page_size=state.page_size,
            )
        return state

    def prev_page(self, state: CarouselState[T]) -> CarouselState[T]:
        """Move to previous item, returns new state."""
        if state.has_prev:
            return CarouselState(
                items=state.items,
                current_index=state.current_index - 1,
                page_size=state.page_size,
            )
        return state

    def go_to_index(self, state: CarouselState[T], index: int) -> CarouselState[T]:
        """Jump to specific index."""
        if 0 <= index < len(state.items):
            return CarouselState(
                items=state.items,
                current_index=index,
                page_size=state.page_size,
            )
        return state

    def select_item(self, state: CarouselState[T]) -> T | None:
        """Get the currently selected item."""
        return state.current_item
