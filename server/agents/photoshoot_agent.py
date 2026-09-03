"""Photoshoot Agent — turning a plain photo into an editorial.

Two different things live here and it is worth keeping them straight, because
they solve the same request in opposite ways:

  * DIRECTION — the shoot you would actually go and do. Lighting diagram, lens,
    location, pose, styling, shot list, call sheet. This is what you use when
    the picture matters and you have a camera.
  * RENDERING — the image itself, generated from your photo as a reference.
    Fast, good for pitching an idea to a client before anyone books a studio.
    It is a mockup, and the agent says so; passing a rendered image off as a
    real shoot is how a stylist loses a client.

Both read the taste profile, so the direction that comes back is yours rather
than a generic magazine pastiche.
"""
from __future__ import annotations

from .. import brain, jsonish, style_memory
from .base import BaseAgent, tool
from .scan_agent import latest_image, resolve_image, uploads_dir

DIRECTION_PROMPT = """\
You are directing an editorial shoot built around the subject in this image.
Think like a photographer and a stylist at once — every choice must be
executable by a small crew, not aspirational mood-board language.

Return ONLY JSON:
{
  "concept": "the idea in one sentence",
  "reference_world": ["photographers, editorials or films this sits beside"],
  "location": {"setting": "", "why": "", "backup": "indoor fallback"},
  "lighting": {"key": "source, modifier, position, height",
               "fill": "", "rim": "", "practicals": "",
               "mood": "hard/soft, warm/cool, contrast ratio"},
  "camera": {"lens": "focal length and why", "aperture": "", "angle": "",
             "distance": "", "movement": "static or handheld"},
  "styling": {"silhouette": "", "layers": [], "fabrics": [],
              "accessories": [], "footwear": ""},
  "hair": "direction a hairstylist can execute",
  "makeup": "direction a makeup artist can execute",
  "posing": ["four to six specific directions to give the subject"],
  "colour_grade": "how it should be graded in post",
  "retouch": ["what to fix, what to leave — be restrained"],
  "shot_list": [{"shot": "", "framing": "", "purpose": ""}],
  "pitfalls": ["what will go wrong on the day if you are not careful"]
}
"""


class PhotoshootAgent(BaseAgent):
    name = "photoshoot"
    description = ("Turns a plain photo into a directed editorial shoot — lighting, "
                   "lens, location, posing, styling and shot list — and can render "
                   "an editorial mockup from the photo as reference.")

    @tool(
        "Direct a full editorial shoot from a photo: lighting, lens, location, "
        "posing, styling, hair, makeup, shot list and retouch notes. Use when the "
        "owner wants to turn a picture into a real photoshoot.",
        image_id={"type": "string",
                  "description": "Photo id; blank uses the newest photo",
                  "required": False},
        concept={"type": "string",
                 "description": "Direction to push toward — a mood, a reference, "
                                "a client brief", "required": False},
    )
    async def direct(self, image_id: str = "", concept: str = ""):
        path = resolve_image(image_id) if image_id else latest_image()
        prompt = DIRECTION_PROMPT
        if concept:
            prompt += f"\nThe direction to push toward: {concept}\n"
        prompt += f"\nThe owner's taste, which this shoot should feel like:\n{style_memory.summary()}\n"
        raw = await brain.look(path, prompt)
        result = jsonish.loads(raw, {})
        if not result:
            return {"error": "could not build a shoot direction from that image",
                    "raw": raw[:500]}
        result["image_id"] = path.name
        return result

    @tool(
        "Render an editorial mockup from a photo — the image itself, not just "
        "direction. Use to show a client or the owner what a look could become. "
        "The result is a mockup, not a real photograph, and you should say so.",
        image_id={"type": "string", "description": "Reference photo id; blank uses "
                                                   "the newest", "required": False},
        direction={"type": "string",
                   "description": "How to restyle it — lighting, wardrobe, mood, "
                                  "location"},
        variations={"type": "string",
                    "description": "How many to render, 1-4 (default 1)",
                    "required": False},
    )
    async def render(self, direction: str, image_id: str = "", variations: str = "1"):
        try:
            path = resolve_image(image_id) if image_id else latest_image()
        except FileNotFoundError:
            path = None  # pure text-to-image is still useful

        count = max(1, min(int(variations or 1), 4))
        prompt = (
            f"Editorial fashion photograph. {direction}. "
            "Shot on medium format, natural skin texture retained, considered "
            "lighting with intentional shadow, magazine-quality composition. "
            "Keep the subject's identity, face and body proportions exactly as in "
            "the reference. Do not beautify or slim the subject."
            if path else
            f"Editorial fashion photograph. {direction}. Shot on medium format, "
            "considered lighting, magazine-quality composition.")

        try:
            images = await brain.imagine(prompt, reference=path, count=count,
                                         out_dir=uploads_dir())
        except brain.NoImageModel as exc:
            return {"error": str(exc),
                    "fallback": "ask me to `direct` the shoot instead — you get the "
                                "full lighting and styling plan without an image model"}
        return {"rendered": [p.name for p in images],
                "reference": path.name if path else None,
                "direction": direction,
                "note": "these are AI mockups for pitching, not photographs"}

    @tool(
        "Build a shot list for a booked shoot — every setup, framing and purpose, "
        "in the order to shoot them.",
        concept={"type": "string", "description": "The shoot concept"},
        looks={"type": "string", "description": "How many looks", "required": False},
        hours={"type": "string", "description": "Hours available", "required": False},
    )
    async def shot_list(self, concept: str, looks: str = "3", hours: str = "4"):
        raw = await brain.complete(
            f"Build a shot list for a {hours}-hour editorial shoot with {looks} looks.\n"
            f"CONCEPT: {concept}\n"
            f"The stylist's taste:\n{style_memory.summary()}\n\n"
            "Order it the way you would actually shoot it — hardest light setup "
            "first, quick-change looks grouped, hero shot while everyone is fresh.\n"
            'Return ONLY JSON: {"schedule": [{"time": "", "look": "", "setup": "", '
            '"shots": [""], "notes": ""}], "crew": [""], "kit": [""], '
            '"risks": [""]}')
        result = jsonish.loads(raw, {})
        return result or {"error": "could not build a shot list", "raw": raw[:400]}

    @tool(
        "Retouch notes for an image — what to fix, what to leave alone.",
        image_id={"type": "string", "description": "Photo id; blank uses newest",
                  "required": False},
    )
    async def retouch_notes(self, image_id: str = ""):
        path = resolve_image(image_id) if image_id else latest_image()
        raw = await brain.look(
            path,
            "Give retouch notes for this image as a retoucher would to an assistant. "
            "Be restrained — modern editorial keeps skin texture and real bodies. "
            'Return ONLY JSON: {"colour": "", "exposure": "", "skin": "", '
            '"garment_fixes": [""], "background": "", "crop": "", '
            '"leave_alone": [""], "order_of_operations": [""]}')
        result = jsonish.loads(raw, {})
        result["image_id"] = path.name
        return result or {"error": "could not read that image"}

    @tool(
        "Write a call sheet for a shoot — crew, times, location, contacts, kit.",
        concept={"type": "string", "description": "The shoot"},
        date={"type": "string", "description": "Shoot date", "required": False},
        location={"type": "string", "description": "Where", "required": False},
    )
    async def call_sheet(self, concept: str, date: str = "", location: str = ""):
        text = await brain.complete(
            f"Write a professional call sheet.\nSHOOT: {concept}\n"
            f"DATE: {date or 'TBC'}\nLOCATION: {location or 'TBC'}\n\n"
            "Include: call times by role, crew list with roles, talent, wardrobe "
            "and kit checklist, schedule blocks, nearest hospital, weather note, "
            "and a contacts block with placeholders. Plain text, no markdown, "
            "formatted to print on one page.")
        return {"concept": concept, "date": date, "location": location,
                "call_sheet": text}
