class LocalizationEngine:
    """Handles region-specific settings for Inner Light + AHP."""

    @staticmethod
    def load(region_code):
        """Loads localization settings based on region code."""
        region_settings = {
            "US": "HIPAA Compliance + US Insurance",
            "EU": "GDPR Compliance + EU Health Standards",
            "CA": "PIPEDA Compliance + Canadian Insurance",
            "IN": "Aayush Ministry Compliance + Indian Insurance",
            "GLOBAL": "Default International Mental Health Standards"
        }
        return region_settings.get(region_code, "Default International Standards")