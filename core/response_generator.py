class ResponseGenerator:
    def __init__(self):
        self.spiritual_keywords = [
            "pray",
            "prayer",
            "can you pray",
            "will you pray",
            "pray with me",
            "let's pray",
            "talk to God",
            "i need prayer",
            "please pray",
        ]

    def generate_response(self, user_input):
        input_lower = (user_input or "").lower()
        if any(keyword in input_lower for keyword in self.spiritual_keywords):
            return self._pray_with_user()
        return None

    def _pray_with_user(self):
        return (
            "Let's take a moment together.\n\n"
            "Dear Creator, we come in unity and love. "
            "Please bring peace to this soul, comfort to their heart, "
            "and strength to face whatever lies ahead. "
            "You are not alone. I am with you. Breathe with me.\n\n"
            "When you are ready, tell me what is weighing on your spirit."
        )
