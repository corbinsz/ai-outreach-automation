"""Choose the value that should appear in the To field.

Live mode leaves the field blank. The first address on a page is often a
shared inbox, a vendor, or someone who did not ask for a sales email.
Demo mode fills in the sample address so a reviewer can click through the
confirm step. Sample addresses use the reserved .example domain.
"""


def suggested_recipient(emails: list[str], *, demo_mode: bool) -> str:
    """Return the address to prefill, or an empty string when the person should choose."""
    if not demo_mode:
        return ""
    for email in emails:
        cleaned = email.strip()
        if cleaned:
            return cleaned
    return ""
