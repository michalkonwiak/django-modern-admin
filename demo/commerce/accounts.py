"""Account administration for the demo workspace.

Modern Admin never exposes user management implicitly; the demo opts in here.
"""

from __future__ import annotations

from modern_admin import site
from modern_admin.accounts import register_accounts

register_accounts(site)
