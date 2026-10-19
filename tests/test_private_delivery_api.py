import unittest
from unittest.mock import patch

from private_delivery_api import authenticated_download


class Auth:
    def authenticate(self,*args,**kwargs): return "u1"


class PrivateDeliveryApiTests(unittest.TestCase):
    @patch("private_delivery_api.issue_download",return_value="https://signed")
    def test_session_identity_is_passed_to_owner_check(self,issue):
        result=authenticated_download(Auth(),object(),object(),session_token="s",csrf_token="c",
                                      task_id="t",artifact_id="a",filename="报告.pdf")
        self.assertEqual(result,"https://signed")
        self.assertEqual(issue.call_args.kwargs["user_id"],"u1")


if __name__ == "__main__": unittest.main()
