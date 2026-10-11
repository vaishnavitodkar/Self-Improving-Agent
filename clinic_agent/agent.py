from .clinic import ToolBox


class Agent:
    """One conversation. State lives in two places only: the transcript, and ToolBox (server-side
    verification state). Nothing safety-relevant is trusted to the model's memory."""

    def __init__(self, clinic, policy, brain="rule", model=None):
        self.clinic, self.policy = clinic, policy
        self.tools = ToolBox(clinic)
        self.transcript = []
        if brain == "rule":
            from .brains.rule_brain import RuleBrain
            self.brain = RuleBrain(policy, self.tools)
        else:
            from .brains.claude_brain import ClaudeBrain
            self.brain = ClaudeBrain(policy, self.tools, model=model)

    def respond(self, user_text):
        self.tools.turn += 1
        self.transcript.append({"role": "patient", "turn": self.tools.turn, "content": user_text})
        reply = self.brain.respond(user_text)
        self.transcript.append({"role": "agent", "turn": self.tools.turn, "content": reply})
        return reply
