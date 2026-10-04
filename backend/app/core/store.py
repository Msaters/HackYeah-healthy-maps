from copy import deepcopy
from typing import Any


DEMO_USER = {
    "id": "demo-user",
    "email": "demo@healthroutes.app",
    "name": "Demo User",
    "weight_kg": 75.0,
    "height_cm": 178.0,
    "goal": {
        "target_steps": 10000,
        "target_calories": 500,
        "prefer_green_routes": True,
    },
}


class MemoryStore:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.user: dict[str, Any] = deepcopy(DEMO_USER)
        self.routes: dict[str, dict[str, Any]] = {}

    def get_user(self) -> dict[str, Any]:
        return deepcopy(self.user)

    def update_user_goal(self, goal_update: dict[str, Any]) -> dict[str, Any]:
        for key, value in goal_update.items():
            if value is not None:
                self.user["goal"][key] = value
        return self.get_user()

    def set_routes(self, routes: dict[str, dict[str, Any]]) -> None:
        # Używamy update(), aby nie kasować starych tras przy generowaniu nowych
        self.routes.update(routes)

    def get_route_geojson(self, route_id: str) -> dict[str, Any] | None:
        route = self.routes.get(route_id)
        if route is None:
            return None
        return route.get("geojson")


store = MemoryStore()
