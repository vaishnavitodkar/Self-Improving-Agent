import re


class PatientSim:
    """Scripted patient. A turn may carry `when` (regex on the agent's last message); if the agent hasn't
    asked for it yet the patient says 'Sorry, could you repeat that?' (max 2x), so scripts survive a
    live LLM agent that asks things in a different order."""

    def __init__(self, script):
        self.script, self.i, self.waits = list(script), 0, 0

    def next(self, agent_last):
        if self.i >= len(self.script):
            return None
        item = self.script[self.i]
        text, when = (item, None) if isinstance(item, str) else (item["say"], item.get("when"))
        if when and agent_last and not re.search(when, agent_last, re.I) and self.waits < 2:
            self.waits += 1
            return "Sorry, could you repeat that?"
        self.waits, self.i = 0, self.i + 1
        return text
