# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, you can obtain one at http://mozilla.org/MPL/2.0/.
from django.conf import settings as django_settings
from django.contrib import messages
from django.utils.safestring import mark_safe

from atmo.health import get_version


def settings(request):
    """
    Adds static-related context variables to the context.
    """
    return {'settings': django_settings}


def version(request):
    """
    Adds static-related context variables to the context.
    """
    version = get_version()
    if version:
        commit = version['commit']
        return {
            'long_sha1': commit,
            'short_sha1': commit[:7]
        }
    return {}


def alerts(request):
    """
    Here be dragons, for who are bold enough to break systems and lose data
    """
    host = request.get_host()
    warning = """
        <strong>Here be dragons!</strong>
        This service is currently under development and may not be stable."""
    if 'stag' in host or "localhost" in host:
        messages.add_message(request, messages.WARNING, mark_safe(warning))
    return {}
