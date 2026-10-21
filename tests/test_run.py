from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN_SCRIPT = ROOT / "rustdesk_server" / "run.sh"


class RunScriptTests(unittest.TestCase):
    def run_app(self, options: dict[str, object]) -> subprocess.CompletedProcess[str]:
        scratch = Path(os.environ.get("TMPDIR", Path.home() / ".hermes/cache/scratch"))
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as temp_dir:
            temp = Path(temp_dir)
            options_file = temp / "options.json"
            options_file.write_text(json.dumps(options), encoding="utf-8")
            init = temp / "init-stub"
            init.write_text(
                "#!/bin/sh\n"
                "cat <<EOF\n"
                "STARTED=1\n"
                "RELAY=$RELAY\n"
                "ENCRYPTED_ONLY=$ENCRYPTED_ONLY\n"
                "MUST_LOGIN=$MUST_LOGIN\n"
                "API_URL=$RUSTDESK_API_RUSTDESK_API_SERVER\n"
                "ID_SERVER=$RUSTDESK_API_RUSTDESK_ID_SERVER\n"
                "RELAY_SERVER=$RUSTDESK_API_RUSTDESK_RELAY_SERVER\n"
                "KEY_FILE=$RUSTDESK_API_RUSTDESK_KEY_FILE\n"
                "REGISTER=$RUSTDESK_API_APP_REGISTER\n"
                "WEB_CLIENT=$RUSTDESK_API_APP_WEB_CLIENT\n"
                "JWT_SET=${RUSTDESK_API_JWT_KEY:+yes}\n"
                "EOF\n",
                encoding="utf-8",
            )
            init.chmod(0o755)
            env = os.environ.copy()
            env.update({"OPTIONS_FILE": str(options_file), "S6_INIT": str(init)})
            return subprocess.run(
                ["/bin/sh", str(RUN_SCRIPT)], capture_output=True, text=True, env=env, check=False
            )

    def test_maps_options_to_full_server_environment(self) -> None:
        result = self.run_app(
            {
                "external_host": "rustdesk.example.net",
                "api_url": "https://rustdesk.example.net",
                "encrypted_only": True,
                "must_login": False,
                "allow_registration": False,
                "jwt_key": "",
            }
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RELAY=rustdesk.example.net:21117", result.stdout)
        self.assertIn("ENCRYPTED_ONLY=1", result.stdout)
        self.assertIn("MUST_LOGIN=N", result.stdout)
        self.assertIn("API_URL=https://rustdesk.example.net", result.stdout)
        self.assertIn("ID_SERVER=rustdesk.example.net:21116", result.stdout)
        self.assertIn("RELAY_SERVER=rustdesk.example.net:21117", result.stdout)
        self.assertIn("KEY_FILE=/data/id_ed25519.pub", result.stdout)
        self.assertIn("REGISTER=false", result.stdout)
        self.assertIn("WEB_CLIENT=1", result.stdout)

    def test_rejects_missing_public_hostname(self) -> None:
        result = self.run_app(
            {
                "external_host": "",
                "api_url": "https://rustdesk.example.net",
                "encrypted_only": True,
                "must_login": False,
                "allow_registration": False,
                "jwt_key": "",
            }
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("external_host", result.stderr)
        self.assertNotIn("STARTED=1", result.stdout)

    def test_rejects_non_http_api_url(self) -> None:
        result = self.run_app(
            {
                "external_host": "rustdesk.example.net",
                "api_url": "rustdesk.example.net",
                "encrypted_only": True,
                "must_login": False,
                "allow_registration": False,
                "jwt_key": "",
            }
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("api_url", result.stderr)
        self.assertNotIn("STARTED=1", result.stdout)

    def test_requires_jwt_key_when_login_is_mandatory(self) -> None:
        result = self.run_app(
            {
                "external_host": "rustdesk.example.net",
                "api_url": "https://rustdesk.example.net",
                "encrypted_only": True,
                "must_login": True,
                "allow_registration": False,
                "jwt_key": "",
            }
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("jwt_key", result.stderr)
        self.assertNotIn("STARTED=1", result.stdout)

    def test_passes_jwt_key_only_to_runtime(self) -> None:
        result = self.run_app(
            {
                "external_host": "rustdesk.example.net",
                "api_url": "https://rustdesk.example.net",
                "encrypted_only": True,
                "must_login": True,
                "allow_registration": False,
                "jwt_key": "test-secret-not-printed",
            }
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("MUST_LOGIN=Y", result.stdout)
        self.assertIn("JWT_SET=yes", result.stdout)
        self.assertNotIn("test-secret-not-printed", result.stdout)


if __name__ == "__main__":
    unittest.main()
