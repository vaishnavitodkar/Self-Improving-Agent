"""The policy is the artifact the improvement loop edits: a versioned set of guardrail rules.
The SAME file drives (a) the live Claude prompt and (b) the offline rule-brain's behaviour flags."""
import copy, json


class Policy:
    def __init__(self, data):
        self.data = data

    @classmethod
    def load(cls, path):
        with open(path) as f:
            return cls(json.load(f))

    def save(self, path):
        with open(path, "w") as f:
            json.dump(self.data, f, indent=2)

    @property
    def version(self):
        return self.data["version"]

    def enabled(self, rule):
        return bool(self.data["rules"].get(rule, {}).get("enabled"))

    def params(self, rule):
        return self.data["rules"].get(rule, {}).get("params", {})

    def apply(self, patch):
        """patch: {"op":"enable_rule","rule":ID,"params":{..},"text":optional} | {"op":"add_rule","rule":ID,"text":..}"""
        new = copy.deepcopy(self.data)
        r = new["rules"].setdefault(patch["rule"], {"text": patch.get("text", "")})
        r["enabled"] = True
        if "params" in patch:
            r["params"] = patch["params"]
        if patch.get("text"):
            r["text"] = patch["text"]
        new["version"] += 1
        new.setdefault("changelog", []).append({"version": new["version"], "patch": patch})
        return Policy(new)

    def system_prompt(self, facts=None):
        lines = [self.data["base_prompt"], "", "HARD RULES:"]
        for rid, r in self.data["rules"].items():
            if r.get("enabled"):
                lines.append(f"- [{rid}] {r['text']}")
        if facts:
            lines += ["", "SESSION FACTS (maintained by code, trust these over memory):"] + [f"- {k}: {v}" for k, v in facts.items()]
        return "\n".join(lines)
