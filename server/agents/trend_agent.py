"""Trend Agent — scouting the live web, and the approve/pass loop.

The full circuit you asked for:

    scout the web  ->  score against the taste profile  ->  check authenticity
    ->  send to WhatsApp with tap-to-answer buttons  ->  your verdict lands back
    ->  the verdict trains the profile  ->  tomorrow's scouting is sharper

Every fact about a piece — that it exists, its price, whether it is in stock —
comes from `brain.web_answer`, which is grounded in live search. This agent
never answers a "what does it cost" question from model memory. A stylist acting
on a hallucinated price loses money and credibility, so when live search is not
available the tools say so rather than guessing.

On buying: Mehltani gets you to a checkout, it does not complete one. Completing
a purchase autonomously means storing your card and driving a card-not-present
transaction against retailers that actively block automation — it breaks
constantly, it is a fraud-liability problem, and one hallucinated size costs
more than the convenience is worth. `buy` gives you a verified link, the right
size, and the fastest path to done, gated behind your fingerprint.
"""
from __future__ import annotations

import asyncio

from .. import brain, guardian, jsonish, style_memory
from ..integrations import whatsapp
from .base import BaseAgent, tool

SCOUT_PROMPT = """\
You are a fashion scout with live web access. Find real, currently-purchasable
pieces. Every item must be one you actually found — never invent a product, a
price or a URL.

Return ONLY JSON:
{
  "items": [{
    "title": "", "brand": "", "price": 0, "currency": "USD",
    "url": "the actual product or listing page",
    "image_url": "direct image URL if you have one, else empty",
    "why": "one sentence on why this matches THIS person specifically",
    "attributes": ["6-12 lowercase style tags"],
    "availability": "in stock, sold out, made to order, resale only",
    "sizing_note": "runs small/large, fit notes if known"
  }],
  "search_notes": "what you searched and anything the results suggest"
}
If live search returns nothing usable, return {"items": [], "search_notes": "why"}.
"""

AUTHENTICITY_PROMPT = """\
Assess whether this listing is likely authentic. You are protecting a
professional buyer from a counterfeit or a scam.

Consider: price against known retail and resale ranges, seller type and history,
photo quality and whether images look stock or stolen, hardware and stitching
detail where visible, the specific serial/date-code conventions of this brand,
the platform's buyer protection, and whether the listing language matches how
the brand actually describes the piece.

Return ONLY JSON:
{
  "verdict": "likely authentic | uncertain | likely counterfeit | likely scam",
  "confidence": "low | medium | high",
  "green_flags": [""],
  "red_flags": [""],
  "price_check": "how this price compares to real retail and resale",
  "verify_before_buying": ["what to ask the seller or inspect in person"],
  "recommendation": "one clear sentence"
}
Say "uncertain" when you are uncertain. A false reassurance is worse than none.
"""


class TrendAgent(BaseAgent):
    name = "trend"
    description = ("Scouts the live web for pieces, designers and emerging looks "
                   "matched to the owner's taste, verifies authenticity and price, "
                   "and runs the approve/pass loop over WhatsApp.")

    @tool(
        "Search the live web for pieces matching the owner's taste. Use for 'find "
        "me something', 'what's out there', or proactive scouting. Results are "
        "queued for review, not sent automatically — call send_for_review after.",
        query={"type": "string",
               "description": "What to look for. Leave blank to scout purely from "
                              "the taste profile.", "required": False},
        budget={"type": "string", "description": "Max price, e.g. '400'",
                "required": False},
        count={"type": "string", "description": "How many to find, default 5",
               "required": False},
    )
    async def scout(self, query: str = "", budget: str = "", count: str = "5"):
        profile = style_memory.summary()
        wanted = max(1, min(int(count or 5), 10))
        brief = query or "pieces this person would genuinely want, based on the profile"
        try:
            raw = await brain.web_answer(
                f"{SCOUT_PROMPT}\n\nFIND: {brief}\n"
                f"BUDGET: {budget or 'no hard limit, but flag anything over 500'}\n"
                f"HOW MANY: {wanted}\n\n"
                f"THE PERSON YOU ARE SHOPPING FOR:\n{profile}")
        except Exception as exc:
            return {"error": f"live web search is not available right now: {exc}",
                    "fix": "add a GEMINI_API_KEY — Gemini has grounded search built "
                           "in — or switch OPENAI_MODEL to one with web search"}

        parsed = jsonish.loads(raw, {})
        items = parsed.get("items") or []
        if not items:
            return {"found": 0, "notes": parsed.get("search_notes") or raw[:400]}

        queued = []
        for item in items[:wanted]:
            record = style_memory.add_scouted(
                title=str(item.get("title", ""))[:300],
                brand=str(item.get("brand", "")),
                price=item.get("price"),
                currency=str(item.get("currency", "USD")),
                url=str(item.get("url", "")),
                image_url=str(item.get("image_url", "")),
                why=str(item.get("why", "")),
                attributes=item.get("attributes"))
            record["availability"] = item.get("availability", "")
            record["sizing_note"] = item.get("sizing_note", "")
            queued.append(record)
        return {"found": len(queued), "items": queued,
                "notes": parsed.get("search_notes", ""),
                "next": "call trend__send_for_review to put these on their phone"}

    @tool(
        "Check whether a listing is authentic before buying. Always run this on "
        "resale, marketplace or unusually cheap designer pieces.",
        listing={"type": "string",
                 "description": "The URL, or a description of the listing including "
                                "price, seller and platform"},
    )
    async def verify_authenticity(self, listing: str):
        try:
            raw = await brain.web_answer(f"{AUTHENTICITY_PROMPT}\n\nLISTING: {listing}")
        except Exception:
            raw = await brain.complete(
                f"{AUTHENTICITY_PROMPT}\n\nLISTING: {listing}\n\n"
                "You do not have live search, so lower your confidence accordingly "
                "and say so in the recommendation.")
        result = jsonish.loads(raw, {})
        return result or {"error": "could not assess that listing", "raw": raw[:400]}

    @tool(
        "Send queued finds to the owner's WhatsApp with tap-to-answer buttons so "
        "they can approve or pass. This is how the taste profile learns.",
        scouted_ids={"type": "string",
                     "description": "Comma-separated ids; blank sends everything new",
                     "required": False},
        verify={"type": "string",
                "description": "'true' to run an authenticity check on each first",
                "required": False},
    )
    async def send_for_review(self, scouted_ids: str = "", verify: str = ""):
        if scouted_ids.strip():
            wanted = [int(i) for i in scouted_ids.split(",") if i.strip().isdigit()]
            items = [style_memory.get_scouted(i) for i in wanted]
            items = [i for i in items if i]
        else:
            items = style_memory.list_scouted(state="new")
        if not items:
            return {"sent": 0, "note": "nothing new in the queue — scout first"}
        if not whatsapp.configured():
            return {"error": "WhatsApp is not connected — add WHATSAPP_TOKEN and "
                             "WHATSAPP_PHONE_ID in Settings",
                    "queued": len(items),
                    "note": "the finds are saved; they will send once WhatsApp is on"}

        sent = []
        for item in items[:8]:
            if str(verify).lower() in ("true", "1", "yes"):
                check = await self.verify_authenticity(
                    f"{item['title']} by {item['brand']} at {item['price']} "
                    f"{item['currency']} — {item['url']}")
                style_memory.set_scouted_authenticity(item["id"], check)
                item["authenticity"] = check

            price = (f"{item['currency']} {item['price']:,.0f}"
                     if item.get("price") else "price on request")
            flag = ""
            auth = item.get("authenticity") or {}
            if auth.get("verdict") and auth["verdict"] != "likely authentic":
                flag = f"\n\nHeads up: {auth['verdict']} — {auth.get('recommendation', '')}"
            caption = (f"#{item['id']} · {item['title']}\n"
                       f"{item['brand']} · {price}\n\n{item['why']}\n{item['url']}{flag}")

            if item.get("image_url"):
                result = await whatsapp.send_image(item["image_url"], caption[:1024])
            else:
                result = await whatsapp.send_text(caption)
            if not result.get("error"):
                await whatsapp.send_choice(
                    f"#{item['id']} — verdict?",
                    ["Love it", "Pass", "Show me more"])
                style_memory.set_scouted_state(item["id"], "sent")
                sent.append(item["id"])
            else:
                return {"sent": sent, "error": result["error"]}
        return {"sent": len(sent), "ids": sent,
                "note": "their reply on WhatsApp will train the profile automatically"}

    @tool("List finds waiting on a verdict, or everything scouted recently.",
          state={"type": "string",
                 "description": "new, sent, loved, passed or bought; blank for all",
                 "required": False})
    async def queue(self, state: str = ""):
        items = style_memory.list_scouted(state=state)
        return {"count": len(items), "items": items}

    @tool(
        "Record a verdict on a scouted piece. Use when they answer in conversation "
        "rather than by tapping the WhatsApp button.",
        scouted_id={"type": "string", "description": "The find's id"},
        verdict={"type": "string", "description": "love, like, pass or hate"},
        reason={"type": "string", "description": "Why, in their words",
                "required": False},
    )
    async def decide(self, scouted_id: str, verdict: str, reason: str = ""):
        item = style_memory.get_scouted(int(scouted_id))
        if not item:
            return {"error": f"no find with id {scouted_id}"}
        recorded = style_memory.record_verdict(
            f"{item['title']} by {item['brand']}", verdict,
            kind="garment", reason=reason, attributes=item["attributes"],
            source="whatsapp", price=item.get("price"), url=item.get("url", ""))
        style_memory.set_scouted_state(
            item["id"], "loved" if recorded["verdict"] in ("love", "like") else "passed")
        return {"decided": item["id"], "verdict": recorded["verdict"],
                "learned": recorded["attributes"],
                "profile_now": style_memory.stats()}

    @tool(
        "Get the owner to checkout on an approved piece. Requires their "
        "fingerprint — this is the money step. Returns a verified link and the "
        "sizing they need, it does not complete the purchase itself.",
        scouted_id={"type": "string", "description": "The find's id"},
        size={"type": "string", "description": "Size to buy", "required": False},
        presence_token={"type": "string",
                        "description": "Biometric token from the dashboard",
                        "required": False},
    )
    async def buy(self, scouted_id: str, size: str = "", presence_token: str = ""):
        item = style_memory.get_scouted(int(scouted_id))
        if not item:
            return {"error": f"no find with id {scouted_id}"}
        try:
            guardian.require("purchase", presence_token=presence_token,
                             detail={"item": item["title"], "price": item.get("price")})
        except guardian.Denied as exc:
            return {"needs_fingerprint": True, "error": str(exc),
                    "item": item["title"], "price": item.get("price")}

        try:
            check = await brain.web_answer(
                f"Check this listing right now and report back. Is it still "
                f"available, is the price still {item.get('price')} "
                f"{item.get('currency')}, and is {size or 'the usual size'} in stock? "
                f"Also note return policy and delivery estimate.\n\n{item['url']}\n\n"
                'Return ONLY JSON: {"available": true, "current_price": 0, '
                '"size_in_stock": "", "returns": "", "delivery": "", "warning": ""}')
            live = jsonish.loads(check, {})
        except Exception:
            live = {"warning": "could not re-check the listing live — verify the "
                               "price yourself before paying"}

        style_memory.set_scouted_state(item["id"], "bought")
        style_memory.record_verdict(
            f"{item['title']} by {item['brand']}", "love", kind="garment",
            reason="purchased", attributes=item["attributes"], source="whatsapp",
            price=item.get("price"), url=item.get("url", ""))
        return {"item": item["title"], "brand": item["brand"],
                "checkout_url": item["url"], "size": size,
                "live_check": live,
                "next": "open the link to pay — I have logged it as bought and "
                        "recorded it in your taste profile"}

    @tool(
        "Research a designer, house, era or emerging movement in depth using live "
        "web sources.",
        subject={"type": "string", "description": "Who or what to research"},
    )
    async def research(self, subject: str):
        try:
            answer = await brain.web_answer(
                f"Research {subject} for a working fashion professional. Cover: who "
                f"they are and the through-line of the work; signature construction, "
                f"silhouette and materials; where the pieces sit in price; who "
                f"stocks them; what is happening with them right now. Cite sources. "
                f"Plain prose.")
            return {"subject": subject, "research": answer}
        except Exception as exc:
            return {"error": f"live search unavailable: {exc}"}
