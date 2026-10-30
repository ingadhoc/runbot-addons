##############################################################################
# For copyright and license notices, see __manifest__.py file in module root
# directory
##############################################################################

from odoo.addons.runbot_merge.git import check
from odoo.addons.runbot_merge.github import MergeError
from odoo.addons.runbot_merge.models.stagings_create import Message

FIXUP_PREFIX = "fixup! "
SQUASH_PREFIX = "squash! "


def _subject(commit):
    # like git: the first paragraph, its lines joined with a space
    return " ".join(commit["commit"]["message"].strip().split("\n\n", 1)[0].splitlines())


def has_autosquash_commits(commits):
    return any(_subject(c).startswith((FIXUP_PREFIX, SQUASH_PREFIX)) for c in commits)


def count_after_autosquash(commits):
    """Number of commits left once the ``fixup!`` and ``squash!`` commits are
    squashed into the commit they fix.
    """
    try:
        return len(group_autosquash(commits))
    except MergeError:
        # the staging reports the commit that does not match
        return len(commits)


def single_after_autosquash(commits):
    """Whether the PR is a single commit once its ``fixup!`` and ``squash!``
    commits are squashed. A PR of one commit is not: the base handles it.
    """
    return len(commits) > 1 and count_after_autosquash(commits) == 1


def _squash_message(target, squashes):
    """Message of ``target`` followed by the body of each ``squash!`` commit,
    without its subject, as ``git rebase --autosquash`` does.
    """
    message = Message.from_message(target["commit"]["message"])
    for commit in squashes:
        squash = Message.from_message(commit["commit"]["message"])
        if body := squash.body.partition("\n")[2].strip():
            message.body = f"{message.body}\n\n{body}"
        # the mergebot adds its own headers to every commit, keep them once
        for key, value in squash.headers.items():
            if key.lower() != "x-original-commit" and value not in message.headers.getlist(key):
                message.headers.add(key, value)
    return str(message)


def fold_squash_messages(groups):
    """Moves the body of each ``squash!`` commit into the message of the
    commit it fixes, and turns it into a ``fixup!``.
    """
    for target, *fixes in groups:
        if squashes := [c for c in fixes if _subject(c).startswith(SQUASH_PREFIX)]:
            target["commit"]["message"] = _squash_message(target, squashes)
            for commit in squashes:
                commit["commit"]["message"] = FIXUP_PREFIX + _subject(commit)[len(SQUASH_PREFIX) :]


def group_autosquash(commits):
    """Groups ``commits`` (oldest first) in autosquash order: each ``fixup!``
    or ``squash!`` commit goes right after the commit it fixes.
    """
    groups = []
    for commit in commits:
        subject = target = _subject(commit)
        while target.startswith((FIXUP_PREFIX, SQUASH_PREFIX)):
            target = target.split(" ", 1)[1]
        if target == subject:
            groups.append([commit])
            continue
        group = next((g for g in groups if _subject(g[0]) == target), None)
        if group is None:
            raise MergeError(f"{commit['sha']} ({subject}) does not match any previous commit of the PR.")
        group.append(commit)
    return groups


def autosquash_range(repo, base, head, original_shas=None):
    """Squashes the ``fixup!`` and ``squash!`` commits of the linear history
    ``base..head`` into the commit they fix.

    :param original_shas: maps each commit to the one to name in errors, e.g.
                          a rebased commit to the commit of the PR
    :returns: the new head, a mapping of each commit to the commit it ended up
              in, and the number of commits left
    """
    original_shas = original_shas or {}
    r = repo.stdout().with_config(text=True, check=False)
    log = check(
        r.log("--reverse", "-z", "--format=%H%n%P%n%an%n%ae%n%ai%n%cn%n%ce%n%B", f"{base}..{head}")
    ).stdout
    commits = []
    for entry in filter(None, log.split("\0")):
        sha, parent, an, ae, ad, cn, ce, message = entry.lstrip("\n").split("\n", 7)
        commits.append(
            {
                "sha": sha,
                "parent": parent,
                "author": (an, ae, ad),
                "committer": (cn, ce),
                "commit": {"message": message},
            }
        )

    groups = group_autosquash(commits)
    if len(groups) == len(commits):
        return head, {c["sha"]: c["sha"] for c in commits}, len(commits)

    new_head, last, in_order, mapping = base, base, True, {}
    for group in groups:
        current = new_head
        for commit in group:
            # while the history keeps its original order, each commit already
            # has the right tree; after the first reordering it is replayed
            if in_order and commit["parent"] == last:
                tree = r.get_tree(commit["sha"])
            else:
                in_order = False
                try:
                    tree = check(r.merge_tree("--merge-base", commit["parent"], current, commit["sha"]))
                except MergeError as e:
                    sha, target_sha = (original_shas.get(c["sha"], c["sha"]) for c in (commit, group[0]))
                    # keep git's error: stage() looks for it to retry without mergiraf
                    raise MergeError(
                        f"{sha} ({_subject(commit)}) conflicts when squashed into {target_sha},"
                        f" run `git rebase -i --autosquash` and push.\n\n{e}"
                    ) from None
                tree = tree.stdout.splitlines()[0]
            current = check(r.commit_tree(tree=tree, parents=[current], message="temp autosquash")).stdout.strip()
            last = commit["sha"]

        first = group[0]
        # like the base rebase: allow empty commits, but not ones emptied by the squash
        if len(group) > 1 and tree == r.get_tree(new_head):
            raise MergeError(
                f"{original_shas.get(first['sha'], first['sha'])} ({_subject(first)}) results in an empty"
                " commit once its fixup! commits are squashed, remove it and push."
            )
        message = first["commit"]["message"]
        if squashes := [c for c in group[1:] if _subject(c).startswith(SQUASH_PREFIX)]:
            message = _squash_message(first, squashes)
        new_head = check(
            r.commit_tree(
                tree=tree,
                parents=[new_head],
                message=message,
                author=first["author"],
                committer=first["committer"],
            )
        ).stdout.strip()
        mapping.update(dict.fromkeys((c["sha"] for c in group), new_head))

    return new_head, mapping, len(groups)
