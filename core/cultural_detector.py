# ahp_protocol/cultural_detector.py

class CulturalDetector:
    def __init__(self):
        self.cultural_keywords = {
            "african_american": ["black", "african american", "my momma", "my people", "the culture"],
            "asian_american": ["asian", "japanese", "korean", "chinese", "my ancestors"],
            "latinx": ["latino", "latina", "puerto rican", "mexican", "barrio", "abuelita"],
            "white": ["white", "caucasian", "trailer", "midwest", "appalachia"]
        }

    def detect_ethnicity(self, text):
        text = text.lower()
        for group, keywords in self.cultural_keywords.items():
            if any(keyword in text for keyword in keywords):
                return group
        return "default"
