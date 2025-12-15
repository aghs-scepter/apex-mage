"""Tests for carousel business logic."""

from src.core.carousel_logic import CarouselController, CarouselState


class TestCarouselState:
    def test_empty_carousel(self):
        state: CarouselState[str] = CarouselState(items=[])
        assert state.total_items == 0
        assert state.current_item is None
        assert not state.has_next
        assert not state.has_prev

    def test_single_item(self):
        state: CarouselState[str] = CarouselState(items=["a"])
        assert state.current_item == "a"
        assert not state.has_next
        assert not state.has_prev

    def test_multiple_items(self):
        state: CarouselState[str] = CarouselState(items=["a", "b", "c"])
        assert state.current_item == "a"
        assert state.has_next
        assert not state.has_prev


class TestCarouselController:
    def test_next_page(self):
        controller: CarouselController[str] = CarouselController()
        state: CarouselState[str] = CarouselState(items=["a", "b", "c"])
        new_state = controller.next_page(state)
        assert new_state.current_index == 1
        assert new_state.current_item == "b"

    def test_prev_page(self):
        controller: CarouselController[str] = CarouselController()
        state: CarouselState[str] = CarouselState(items=["a", "b", "c"], current_index=2)
        new_state = controller.prev_page(state)
        assert new_state.current_index == 1

    def test_next_at_end_stays(self):
        controller: CarouselController[str] = CarouselController()
        state: CarouselState[str] = CarouselState(items=["a", "b"], current_index=1)
        new_state = controller.next_page(state)
        assert new_state.current_index == 1  # Unchanged

    def test_prev_at_start_stays(self):
        controller: CarouselController[str] = CarouselController()
        state: CarouselState[str] = CarouselState(items=["a", "b"], current_index=0)
        new_state = controller.prev_page(state)
        assert new_state.current_index == 0  # Unchanged

    def test_go_to_valid_index(self):
        controller: CarouselController[str] = CarouselController()
        state: CarouselState[str] = CarouselState(items=["a", "b", "c"])
        new_state = controller.go_to_index(state, 2)
        assert new_state.current_index == 2

    def test_go_to_invalid_index(self):
        controller: CarouselController[str] = CarouselController()
        state: CarouselState[str] = CarouselState(items=["a", "b", "c"])
        new_state = controller.go_to_index(state, 10)
        assert new_state.current_index == 0  # Unchanged

    def test_select_item(self):
        controller: CarouselController[str] = CarouselController()
        state: CarouselState[str] = CarouselState(items=["a", "b", "c"], current_index=1)
        item = controller.select_item(state)
        assert item == "b"

    def test_select_item_empty(self):
        controller: CarouselController[str] = CarouselController()
        state: CarouselState[str] = CarouselState(items=[])
        item = controller.select_item(state)
        assert item is None
