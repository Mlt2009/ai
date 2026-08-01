"""Home Agent — controls Home Assistant over its REST API."""
from __future__ import annotations

import json

import httpx

from .. import config
from .base import BaseAgent, tool


class HomeAgent(BaseAgent):
    name = "home"
    description = "Controls smart-home devices through Home Assistant: lights, switches, climate, scenes, and sensor readings."

    def _client(self) -> httpx.AsyncClient:
        if not config.HA_TOKEN:
            raise RuntimeError("HA_TOKEN is not configured (.env)")
        return httpx.AsyncClient(
            base_url=f"{config.HA_URL}/api",
            headers={"Authorization": f"Bearer {config.HA_TOKEN}"},
            timeout=10,
        )

    @tool(
        "List Home Assistant entities, optionally filtered by domain "
        "(light, switch, climate, sensor, media_player, scene, ...).",
        domain={"type": "string", "description": "Entity domain filter", "required": False},
    )
    async def list_entities(self, domain: str = ""):
        async with self._client() as c:
            r = await c.get("/states")
            r.raise_for_status()
            out = []
            for s in r.json():
                eid = s["entity_id"]
                if domain and not eid.startswith(domain + "."):
                    continue
                out.append({
                    "entity_id": eid,
                    "state": s.get("state"),
                    "name": s.get("attributes", {}).get("friendly_name", eid),
                })
            return out[:120]

    @tool(
        "Get the current state and attributes of one entity.",
        entity_id={"type": "string", "description": "e.g. light.living_room"},
    )
    async def get_state(self, entity_id: str):
        async with self._client() as c:
            r = await c.get(f"/states/{entity_id}")
            r.raise_for_status()
            s = r.json()
            return {
                "entity_id": entity_id,
                "state": s.get("state"),
                "attributes": s.get("attributes", {}),
            }

    @tool(
        "Call any Home Assistant service — the universal control. Examples: "
        "domain=light service=turn_on data={'entity_id':'light.kitchen','brightness_pct':50}; "
        "domain=climate service=set_temperature data={'entity_id':'climate.home','temperature':22}.",
        domain={"type": "string", "description": "Service domain, e.g. light, switch, climate, scene, media_player"},
        service={"type": "string", "description": "Service name, e.g. turn_on, turn_off, toggle, set_temperature"},
        data={"type": "string", "description": "Service data as a JSON object string incl. entity_id", "required": False},
    )
    async def call_service(self, domain: str, service: str, data: str | dict | None = None):
        if isinstance(data, str):
            data = json.loads(data) if data.strip() else {}
        async with self._client() as c:
            r = await c.post(f"/services/{domain}/{service}", json=data or {})
            r.raise_for_status()
            return {"ok": True, "domain": domain, "service": service, "data": data}

    @tool(
        "Turn a device on or off by entity id.",
        entity_id={"type": "string", "description": "e.g. light.bedroom or switch.fan"},
        on={"type": "boolean", "description": "true = on, false = off"},
    )
    async def set_power(self, entity_id: str, on: bool):
        domain = entity_id.split(".")[0]
        service = "turn_on" if on else "turn_off"
        return await self.call_service(domain, service, {"entity_id": entity_id})
