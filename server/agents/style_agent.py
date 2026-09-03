"""Style Agent — the eye. Reads looks, learns taste, and holds the line on it.

This is the agent that makes Mehltani specific to you rather than a generic
assistant with a fashion vocabulary. Two jobs:

  * judge — look at a garment, an outfit or a mood board and say something
    useful about proportion, palette, texture and context, in the language a
    working stylist actually uses.
  * remember — turn every reaction into structured signal in style_memory, so
    the hundredth judgement is informed by the ninety-nine before it.

The critique prompts deliberately ask for a verdict *and* the reasoning behind
it. A rating with no reasoning teaches the profile nothing, and cannot be
argued with — which is the most useful thing a creative director does.
"""
from __future__ import annotations

from .. import brain, jsonish, style_memory
from ..integrations import glasses
from .base import BaseAgent, tool
from .scan_agent import latest_image, resolve_image

CRITIQUE_PROMPT = """\
You are a senior creative director reviewing a look. Be specific and technical,
never generic praise. Name what is actually happening in the image.

Return ONLY JSON in this shape:
{
  "summary": "one sentence on what this look is doing",
  "garments": ["each visible piece, with fabric and cut if readable"],
  "palette": ["dominant colours, named precisely — 'oxblood' not 'red'"],
  "silhouette": "the shape it creates on the body",
  "proportion": "what is working or fighting, in proportion terms",
  "texture": "fabric and finish interplay",
  "styling_notes": ["concrete changes that would sharpen it"],
  "references": ["designers, eras or shows this sits near"],
  "attributes": ["8-16 lowercase tags for the taste profile: silhouette,
                  colour, era, mood, fabric, styling"],
  "occasion": "where this look belongs",
  "rating": 1-10
}
"""


class StyleAgent(BaseAgent):
    name = "style"
    description = ("The eye: critiques looks, reads palettes and proportion, and "
                   "maintains the owner's learned taste profile — what they love, "
                   "what they reject, and why.")

    @tool(
        "Critique a look, garment or mood board from a photo. Returns structured "
        "notes on palette, silhouette, proportion and references, plus tags for "
        "the taste profile. Use whenever the owner asks what you think of a look.",
        image_id={"type": "string",
                  "description": "Photo id; leave blank for the newest photo",
                  "required": False},
        context={"type": "string",
                 "description": "What it is for — client, occasion, brief",
                 "required": False},
    )
    async def critique(self, image_id: str = "", context: str = ""):
        path = resolve_image(image_id) if image_id else latest_image()
        profile = style_memory.summary()
        prompt = CRITIQUE_PROMPT
        if context:
            prompt += f"\nCONTEXT: {context}\n"
        prompt += (f"\nThe owner's established taste, for reference — note where "
                   f"this look agrees or clashes with it:\n{profile}\n")
        raw = await brain.look(path, prompt)
        result = jsonish.loads(raw, {})
        if not result:
            return {"error": "could not read a structured critique from that image",
                    "raw": raw[:500]}
        result["image_id"] = path.name
        return result

    @tool(
        "Compare two or more looks and rank them against the owner's taste. Use "
        "when they are choosing between options.",
        image_ids={"type": "string",
                   "description": "Comma-separated photo ids to compare"},
        brief={"type": "string", "description": "What they are choosing for",
               "required": False},
    )
    async def compare(self, image_ids: str, brief: str = ""):
        ids = [i.strip() for i in image_ids.split(",") if i.strip()]
        if len(ids) < 2:
            return {"error": "give at least two image ids to compare"}
        reads = []
        for image_id in ids[:4]:
            path = resolve_image(image_id)
            summary = await brain.look(
                path, "Describe this look in three sentences: garments, palette, "
                      "silhouette. Be concrete and technical.")
            reads.append(f"[{image_id}] {summary}")
        verdict = await brain.complete(
            f"You are the owner's creative director. Their taste profile:\n"
            f"{style_memory.summary()}\n\n"
            f"{'Brief: ' + brief if brief else ''}\n\n"
            f"The options:\n" + "\n\n".join(reads) +
            "\n\nRank them best to worst for this person. For each, one line on why. "
            "End with a single clear recommendation. Plain prose, no markdown.")
        return {"compared": ids, "verdict": verdict}

    @tool(
        "Record the owner's verdict on something so the taste profile learns. Call "
        "this every time they react to a look — 'love it', 'not for me', 'the cut "
        "is wrong'. This is how you get better at scouting.",
        subject={"type": "string", "description": "What was judged"},
        verdict={"type": "string", "description": "love, like, pass or hate"},
        reason={"type": "string", "description": "Their reasoning, in their words",
                "required": False},
        attributes={"type": "string",
                    "description": "Comma-separated tags: silhouette, colour, era, "
                                   "fabric, mood", "required": False},
        kind={"type": "string",
              "description": "look, garment, hair, makeup, palette or location",
              "required": False},
    )
    async def record_verdict(self, subject: str, verdict: str, reason: str = "",
                             attributes: str = "", kind: str = "look"):
        # Infer tags when the caller did not supply them — an untagged verdict
        # trains nothing, and the model has the subject text right there.
        if not attributes.strip():
            guessed = await brain.complete(
                "Extract 6-12 lowercase style tags from this note. Cover silhouette, "
                "colour, era, fabric, and mood where present. Return only a JSON "
                f"array of strings.\n\nNOTE: {subject}. {reason}")
            tags = jsonish.loads(guessed, [])
            attributes = ",".join(t for t in tags if isinstance(t, str))[:400]
        return style_memory.record_verdict(
            subject, verdict, kind=kind, reason=reason, attributes=attributes)

    @tool("Read back the learned taste profile — what they gravitate to, what they "
          "reject, and how much evidence there is behind each.")
    async def profile(self):
        return {"summary": style_memory.summary(),
                "attributes": style_memory.attribute_scores()[:40],
                "stated_rules": style_memory.list_traits(),
                "stats": style_memory.stats()}

    @tool(
        "Record a rule the owner stated outright, like 'I never wear yellow' or "
        "'always a strong shoulder'. Stated rules outrank inferred preferences.",
        rule={"type": "string", "description": "Short key, e.g. 'colour:no-yellow'"},
        note={"type": "string", "description": "The rule in their own words"},
    )
    async def set_rule(self, rule: str, note: str):
        return style_memory.set_trait(rule, note, pinned=True)

    @tool("Remove a stated rule that no longer applies.",
          rule={"type": "string", "description": "The rule key to forget"})
    async def forget_rule(self, rule: str):
        return {"forgotten": style_memory.forget_trait(rule), "rule": rule}

    @tool(
        "Build a palette from a photo, an idea or a season — named colours with "
        "hex values, ready to hand to a fabric supplier or a colourist.",
        source={"type": "string",
                "description": "A photo id, or a description like 'late autumn, "
                               "wet stone, one acid note'"},
    )
    async def palette(self, source: str):
        looks_like_image = "." in source and len(source.split()) == 1
        if looks_like_image:
            path = resolve_image(source)
            raw = await brain.look(path, PALETTE_PROMPT)
        else:
            raw = await brain.complete(f"{PALETTE_PROMPT}\n\nSOURCE: {source}")
        result = jsonish.loads(raw, {})
        return result or {"error": "could not build a palette", "raw": raw[:400]}

    @tool(
        "Save a finished look to the lookbook so it can be recalled, shot or sent.",
        title={"type": "string", "description": "Name of the look"},
        brief={"type": "string", "description": "The idea behind it", "required": False},
        pieces={"type": "string", "description": "Comma-separated garments",
                "required": False},
        hair={"type": "string", "description": "Hair direction", "required": False},
        makeup={"type": "string", "description": "Makeup direction", "required": False},
        client={"type": "string", "description": "Who it is for", "required": False},
        occasion={"type": "string", "description": "Where it is worn", "required": False},
    )
    async def save_look(self, title: str, brief: str = "", pieces: str = "",
                        hair: str = "", makeup: str = "", client: str = "",
                        occasion: str = ""):
        return style_memory.add_look(
            title, brief=brief, pieces=[p.strip() for p in pieces.split(",") if p.strip()],
            hair=hair, makeup=makeup, client=client, occasion=occasion)

    @tool("List saved looks from the lookbook.",
          status={"type": "string", "description": "draft, approved, shot or archived",
                  "required": False})
    async def looks(self, status: str = ""):
        found = style_memory.list_looks(status=status)
        return {"count": len(found), "looks": found}

    @tool(
        "Look at whatever the glasses last captured and say what it is, styled. "
        "Use for 'what am I looking at' or 'is this worth buying'.",
        question={"type": "string", "description": "What they want to know",
                  "required": False},
    )
    async def read_the_room(self, question: str = ""):
        fresh = glasses.ingest()
        try:
            path = latest_image()
        except FileNotFoundError:
            return {"error": "nothing has come through yet — send a photo over "
                             "WhatsApp, or set GLASSES_WATCH_DIR to your synced "
                             "camera roll",
                    "how": glasses.status()}
        answer = await brain.look(
            path,
            f"You are a stylist standing next to the person wearing these glasses. "
            f"{question or 'What am I looking at, and is it any good?'}\n\n"
            f"Their taste:\n{style_memory.summary()}\n\n"
            "Answer in two or three spoken sentences. Be direct and specific. No markdown.")
        return {"image_id": path.name, "answer": answer,
                "newly_ingested": len(fresh)}


PALETTE_PROMPT = """\
Build a working colour palette. Return ONLY JSON:
{
  "name": "the palette's name",
  "mood": "one line on what it evokes",
  "colours": [{"name": "precise name like 'oxblood'", "hex": "#5a1a1f",
               "role": "dominant | secondary | accent | neutral",
               "note": "where to use it"}],
  "avoid": ["colours that would break this palette"],
  "fabric_notes": "how these read in different fabrics and finishes"
}
Six to eight colours. Name them precisely — a supplier has to match this.
"""
