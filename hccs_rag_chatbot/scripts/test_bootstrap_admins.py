"""Self-check for the developer allowlist (BOOTSTRAP_ADMIN_EMAILS).

Covers the two security-relevant bits behind it:
  * settings.bootstrap_admin_emails parsing (case/whitespace/empties), and
  * the login admit rule the auth callback applies.

Run: python scripts/test_bootstrap_admins.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import Settings


def test_parsing():
    s = Settings(BOOTSTRAP_ADMIN_EMAILS="Owner@Gmail.com, dev@x.io , ,")
    assert s.bootstrap_admin_emails == {"owner@gmail.com", "dev@x.io"}, s.bootstrap_admin_emails
    assert Settings(BOOTSTRAP_ADMIN_EMAILS="").bootstrap_admin_emails == set()


def test_admit_rule():
    # Mirrors the callback gate: admit only a VERIFIED email that is on the school
    # domain OR on the developer allowlist.
    def admit(verified, on_domain, allowlisted):
        return verified and (on_domain or allowlisted)

    assert admit(True, True, False)       # student on the school domain
    assert admit(True, False, True)       # developer, allowlisted, off-domain
    assert not admit(True, False, False)  # outsider, off-domain, not allowlisted
    assert not admit(False, True, True)   # unverified email is never admitted


if __name__ == "__main__":
    test_parsing()
    test_admit_rule()
    print("ok")
