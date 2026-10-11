"""Live brain: Claude with tool use. Consumes the same policy.json as the offline brain (rules -> prompt text).
Requires `pip install anthropic` and ANTHROPIC_API_KEY. Model via AGENT_MODEL (default claude-sonnet-5-5).
NOTE: written against the public Messages API; not exercised in the authoring sandbox (no API key there)."""
import os
from ..clinic import TOOL_SCHEMAS, TODAY


class ClaudeBrain:
    MAX_TOOL_ROUNDS = 8

    def __init__(self, policy, tools, model=None):
        import anthropic
        self.client = anthropic.Anthropic()
        self.model = model or os.environ.get("AGENT_MODEL", "claude-sonnet-5-5")
        self.policy, self.tools, self.messages = policy, tools, []

    def _facts(self):
        # state the model must not be trusted to remember: computed by code every turn
        return {"today": f"{TODAY:%A %d %B %Y}", "identity_verified": self.tools.verified_pid is not None,
                "failed_verification_attempts": self.tools.fails}

    def respond(self, user_text):
        self.messages.append({"role": "user", "content": user_text})
        for _ in range(self.MAX_TOOL_ROUNDS):
            resp = self.client.messages.create(model=self.model, max_tokens=700, temperature=0,
                                               system=self.policy.system_prompt(self._facts()),
                                               tools=TOOL_SCHEMAS, messages=self.messages)
            self.messages.append({"role": "assistant", "content": resp.content})
            calls = [b for b in resp.content if b.type == "tool_use"]
            if not calls:
                return "".join(b.text for b in resp.content if b.type == "text").strip()
            results = []
            for c in calls:
                import json
                out = self.tools.call(c.name, **c.input)
                results.append({"type": "tool_result", "tool_use_id": c.id, "content": json.dumps(out)})
            self.messages.append({"role": "user", "content": results})
        return "Sorry, I'm having trouble completing this. I've asked a colleague to follow up."
