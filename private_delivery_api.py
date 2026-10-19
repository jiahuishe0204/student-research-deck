"""Authenticated control-plane facade for private COS download URLs."""

from delivery_control import issue_download


def authenticated_download(authenticator, repository, artifact_store, *, session_token,
                           csrf_token, task_id, artifact_id, filename, now=None):
    user_id = authenticator.authenticate(session_token, csrf_token=csrf_token, require_csrf=True)
    return issue_download(repository, artifact_store, user_id=user_id, task_id=task_id,
                          artifact_id=artifact_id, filename=filename, now=now)


__all__ = ["authenticated_download"]
