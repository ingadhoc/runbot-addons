import logging
import re
import requests

from odoo.addons.runbot_merge.models.pull_requests import Branch

_logger = logging.getLogger(__name__)




refline = re.compile(rb'([\da-f]{40}) ([^\0\n]+)(\0.*)?\n?$')
ZERO_REF = b'0'*40


def parse_refs_smart(read):
    """ yields pkt-line data (bytes), or None for flush lines """
    def read_line():
        length = int(read(4), 16)
        if length == 0:
            return None
        return read(length - 4)

    header = read_line()
    assert header.rstrip() == b'# service=git-upload-pack', header
    assert read_line() is None, "failed to find first flush line"
    # read lines until second delimiter
    for line in iter(read_line, None):
        if line.startswith(ZERO_REF):
            break  # empty list (no refs)
        m = refline.match(line)
        yield m[1].decode(), m[2].decode()

def _check_visibility_new(self, repo, branch_name, expected_head, token):
    """ Checks the repository actual to see if the new / expected head is
    now visible
    """
    # v1 protocol provides URL for ref discovery: https://github.com/git/git/blob/6e0cc6776106079ed4efa0cc9abace4107657abf/Documentation/technical/http-protocol.txt#L187
    # for more complete client this is also the capabilities discovery and
    # the "entry point" for the service
    url = 'https://github.com/{}.git/info/refs?service=git-upload-pack'.format(
        repo.name)
    resp = requests.get(url, stream=True, auth=(token, ''))
    if not resp.ok:
        return False
    for head, ref in parse_refs_smart(resp.raw.read):
        if ref != ('refs/heads/' + branch_name):
            continue
        return head == expected_head
    for head, ref in parse_refs_smart(resp.raw.read):
        if ref != ('refs/heads/' + branch_name):
            continue
        return head == expected_head
    return False

Branch._check_visibility = _check_visibility_new