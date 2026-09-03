"""Glam Agent — hair and makeup, at working-artist depth.

The distinction that matters: a chatbot describes a look, an assistant to a
working artist gives an execution. Everything here returns steps, products by
category, timings, and the failure modes — the things you need when you are
behind a chair or on set with forty minutes and a call time.

Two guardrails baked into the prompts:

  * Products are named by *category and property* ("a peptide-bond builder",
    "a silicone-free heat protectant to 230C") rather than by brand. Brand
    recommendations from a model go stale and are frequently invented; a
    category recommendation stays true and lets the artist use what is in
    their own kit.
  * Anything that can damage hair or skin — bleach, relaxers, peels, lash
    adhesive near the eye — comes back with the risk stated plainly rather than
    smoothed over. This is a professional tool, and a burned scalp is a lawsuit.
"""
from __future__ import annotations

from .. import brain, jsonish, style_memory
from .base import BaseAgent, tool
from .scan_agent import latest_image, resolve_image

FACE_READ_PROMPT = """\
Read this face the way a working makeup artist and hairstylist would before
starting. Be observational and technical, never flattering or judgemental.

Return ONLY JSON:
{
  "face_shape": "and the two features that determine it",
  "bone_structure": "cheekbone, jaw and brow notes relevant to contour",
  "undertone": "cool, warm, neutral or olive — and what you read it from",
  "depth": "fair, light, medium, tan, deep, rich — with a shade-match note",
  "eye_shape": "and what that means for liner and lash placement",
  "brow": "current shape and what would suit",
  "lip": "shape and proportion notes",
  "skin_observations": ["texture, tone, anything a base needs to work around"],
  "hair": {"texture": "1a-4c where readable", "density": "", "porosity_guess": "",
           "current_state": "", "length": ""},
  "flattering": ["specific techniques and colours that will work"],
  "avoid": ["what will fight this face or hair, and why"]
}
If something is not readable from the image, say "not readable" — do not guess.
"""


class GlamAgent(BaseAgent):
    name = "glam"
    description = ("Hair and makeup at professional depth — face and hair reads, "
                   "step-by-step looks with timings and products by category, "
                   "colour formulation guidance, and longevity for set or event.")

    @tool(
        "Read a face and hair from a photo before starting work — shape, undertone, "
        "depth, eye and brow, hair texture and porosity, with what suits and what "
        "to avoid. Use before designing any hair or makeup look.",
        image_id={"type": "string", "description": "Photo id; blank uses newest",
                  "required": False},
    )
    async def read_face(self, image_id: str = ""):
        path = resolve_image(image_id) if image_id else latest_image()
        raw = await brain.look(path, FACE_READ_PROMPT)
        result = jsonish.loads(raw, {})
        if not result:
            return {"error": "could not read that image", "raw": raw[:400]}
        result["image_id"] = path.name
        return result

    @tool(
        "Design a makeup look as an executable sequence — steps, timings, products "
        "by category, and how to make it hold.",
        look={"type": "string", "description": "The look: 'wet skin, bare lip, "
                                               "graphic liner'"},
        conditions={"type": "string",
                    "description": "Where it has to survive — flash photography, "
                                   "humidity, twelve-hour day, HD video",
                    "required": False},
        image_id={"type": "string", "description": "Photo of the face, if there is one",
                  "required": False},
    )
    async def makeup(self, look: str, conditions: str = "", image_id: str = ""):
        face = ""
        if image_id:
            read = await self.read_face(image_id)
            face = f"\nThe face you are working on:\n{read}\n"
        raw = await brain.complete(
            f"Design this makeup look as an executable sequence for a working artist.\n"
            f"LOOK: {look}\n"
            f"CONDITIONS: {conditions or 'standard indoor event'}\n{face}\n"
            f"The artist's aesthetic:\n{style_memory.summary()}\n\n"
            "Name products by CATEGORY and PROPERTY, never by brand.\n"
            'Return ONLY JSON: {"look": "", "total_minutes": 0, '
            '"prep": [{"step": "", "product": "", "minutes": 0, "why": ""}], '
            '"steps": [{"step": "", "product": "", "technique": "", "minutes": 0, '
            '"why": ""}], "setting": "how to lock it", '
            '"longevity": "what fails first and the fix", '
            '"under_flash": "how it photographs", "touch_up_kit": [""], '
            '"common_mistakes": [""]}')
        result = jsonish.loads(raw, {})
        return result or {"error": "could not design that look", "raw": raw[:400]}

    @tool(
        "Design a hair look — sectioning, tools, heat settings, timings and hold.",
        look={"type": "string", "description": "The hair look wanted"},
        hair_type={"type": "string",
                   "description": "Texture, density, length, current state",
                   "required": False},
        conditions={"type": "string", "description": "Humidity, duration, movement",
                    "required": False},
    )
    async def hair(self, look: str, hair_type: str = "", conditions: str = ""):
        hair_note = hair_type or "not specified — cover the two or three most likely textures separately"
        raw = await brain.complete(
            f"Design this hair look as an executable sequence for a working stylist.\n"
            f"LOOK: {look}\nHAIR: {hair_note}\n"
            f"CONDITIONS: {conditions or 'standard'}\n\n"
            "Products by CATEGORY and PROPERTY, never brand. Give heat settings in "
            "Celsius with the damage threshold for that texture.\n"
            'Return ONLY JSON: {"look": "", "total_minutes": 0, '
            '"prep": [{"step": "", "product": "", "why": ""}], '
            '"sectioning": "", "tools": [""], "heat": "settings and the ceiling '
            'for this texture", "steps": [{"step": "", "technique": "", '
            '"minutes": 0}], "finish": "", "hold_strategy": "", '
            '"humidity_plan": "", "takedown": "how to get it out safely", '
            '"damage_risks": [""]}')
        result = jsonish.loads(raw, {})
        return result or {"error": "could not design that look", "raw": raw[:400]}

    @tool(
        "Colour guidance — formulation direction, lift and tone, timing and the "
        "honest risk assessment. Always states damage risk plainly.",
        goal={"type": "string", "description": "Target colour and finish"},
        current={"type": "string",
                 "description": "Current level, tone, and any chemical history — "
                                "box dye, henna, previous bleach, relaxer"},
    )
    async def colour(self, goal: str, current: str):
        raw = await brain.complete(
            f"You are advising a licensed colourist. Be technical and be honest "
            f"about damage — never talk someone into a service their hair cannot "
            f"take.\nGOAL: {goal}\nCURRENT: {current}\n\n"
            'Return ONLY JSON: {"achievable_in_one_session": true, '
            '"sessions_needed": 1, "starting_level": "", "target_level": "", '
            '"lift_required": "", "approach": "", '
            '"formulation_direction": "developer volume, tone family, ratio '
            'guidance — not a brand formula", "processing": "timings and checks", '
            '"toning": "", "risks": [""], "deal_breakers": ["conditions where you '
            'refuse the service"], "strand_test": "what to test and what result '
            'means go", "aftercare": [""], "maintenance_weeks": 0}\n\n'
            "If the history includes henna, box dye or a relaxer, say explicitly "
            "what that does to lift and whether to refuse.")
        result = jsonish.loads(raw, {})
        return result or {"error": "could not assess that", "raw": raw[:400]}

    @tool(
        "Match hair and makeup to a styled look so the whole thing reads as one "
        "idea rather than three good ideas fighting.",
        look_description={"type": "string", "description": "The wardrobe/styling"},
        image_id={"type": "string", "description": "Photo of the look",
                  "required": False},
    )
    async def match_to_look(self, look_description: str, image_id: str = ""):
        seen = ""
        if image_id:
            path = resolve_image(image_id)
            seen = await brain.look(path, "Describe the wardrobe, palette, silhouette "
                                          "and mood of this look in four sentences.")
        raw = await brain.complete(
            f"Hair and makeup have to serve this look, not compete with it.\n"
            f"LOOK: {look_description}\n{seen}\n"
            f"The stylist's taste:\n{style_memory.summary()}\n\n"
            'Return ONLY JSON: {"reading": "what the look is saying", '
            '"hair": {"direction": "", "why": "", "execution": ""}, '
            '"makeup": {"direction": "", "why": "", "execution": ""}, '
            '"nails": "", "the_one_rule": "the single thing that would break this '
            'if ignored", "alternatives": [{"if": "", "then": ""}]}')
        result = jsonish.loads(raw, {})
        return result or {"error": "could not match to that look", "raw": raw[:400]}

    @tool(
        "Save or update a client's profile — colouring, hair type, allergies, "
        "measurements, notes. Recall it before their next appointment.",
        name={"type": "string", "description": "Client name"},
        colouring={"type": "string", "description": "Undertone, depth, hair, eyes",
                   "required": False},
        hair_type={"type": "string", "description": "Texture, density, history",
                   "required": False},
        allergies={"type": "string", "description": "Sensitivities and allergies",
                   "required": False},
        notes={"type": "string", "description": "Anything else worth remembering",
               "required": False},
        pronouns={"type": "string", "description": "Their pronouns", "required": False},
    )
    async def client(self, name: str, colouring: str = "", hair_type: str = "",
                     allergies: str = "", notes: str = "", pronouns: str = ""):
        return style_memory.upsert_client(
            name, colouring=colouring, hair_type=hair_type, allergies=allergies,
            notes=notes, pronouns=pronouns)

    @tool("List every client on file, or look one up by name.",
          name={"type": "string", "description": "Leave blank to list all",
                "required": False})
    async def clients(self, name: str = ""):
        if name:
            found = style_memory.get_client(name)
            return found or {"error": f"no client named {name!r} on file"}
        found = style_memory.list_clients()
        return {"count": len(found), "clients": found}
