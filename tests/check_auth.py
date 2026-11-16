"""
tests/check_auth.py
====================
Diagnostic script for IBM watsonx.ai authentication.
Run from anywhere inside the project:

    python AgriDoctor/tests/check_auth.py

This script NEVER prints credential values — only lengths, prefixes, and
structural properties.  Exit code 0 = auth OK, 1 = failure.

Steps tested
────────────
1.  .env file exists at the project root and loads successfully
2.  All required keys are present, non-empty, and structurally valid
3.  ibm-watsonx-ai SDK is importable
4.  Credentials() object can be created
5.  IBM Cloud IAM token exchange succeeds (live network call)
6.  ModelInference() objects can be constructed (validate=False — no API call)
"""

import os
import sys
import json
import urllib.request
import urllib.error
import urllib.parse

# ── Ensure project root is on sys.path ──────────────────────────────────────
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dotenv import load_dotenv

_PASS = 0
_FAIL = 0


def _ok(msg: str):
    global _PASS
    _PASS += 1
    print(f"  OK   {msg}")


def _fail(msg: str, fix: str = ""):
    global _FAIL
    _FAIL += 1
    print(f"  FAIL {msg}")
    if fix:
        print(f"  FIX  {fix}")


# ════════════════════════════════════════════════════════════════════════════
# Step 1 — .env file
# ════════════════════════════════════════════════════════════════════════════
print("=" * 60)
print("Step 1 : .env file")
print("=" * 60)

env_path = os.path.join(_ROOT, ".env")
print(f"  Expected path : {env_path}")

if not os.path.isfile(env_path):
    _fail(
        f".env not found at {env_path}",
        "Copy .env.example to .env and fill in your IBM watsonx.ai credentials.",
    )
    sys.exit(1)
_ok(f".env exists ({os.path.getsize(env_path)} bytes)")

loaded = load_dotenv(env_path, override=True)
if loaded:
    _ok("load_dotenv() loaded at least one key from the file")
else:
    _fail(
        "load_dotenv() returned False — file may be empty or already loaded",
        "Check that .env contains WATSONX_API_KEY=... lines (no extra quotes).",
    )

# ════════════════════════════════════════════════════════════════════════════
# Step 2 — Credential presence and structure
# ════════════════════════════════════════════════════════════════════════════
print()
print("=" * 60)
print("Step 2 : Credential presence and structure")
print("=" * 60)

api_key    = os.getenv("WATSONX_API_KEY",    "").strip()
project_id = os.getenv("WATSONX_PROJECT_ID", "").strip()
url        = (os.getenv("WATSONX_URL", "").strip()
              or "https://us-south.ml.cloud.ibm.com")

# WATSONX_API_KEY checks
if not api_key:
    _fail("WATSONX_API_KEY is empty or missing",
          "Add WATSONX_API_KEY=<your_key> to AgriDoctor/.env")
else:
    has_spaces = " " in api_key
    has_quotes = api_key[0] in ('"', "'") or api_key[-1] in ('"', "'")
    _ok(f"WATSONX_API_KEY present (len={len(api_key)}, first4={api_key[:4]!r})")
    if has_spaces:
        _fail("WATSONX_API_KEY contains whitespace",
              "Remove accidental spaces around the value in .env")
    if has_quotes:
        _fail("WATSONX_API_KEY is wrapped in quotes",
              "Write it as: WATSONX_API_KEY=abc123  (no surrounding quotes)")

# WATSONX_PROJECT_ID checks
if not project_id:
    _fail("WATSONX_PROJECT_ID is empty or missing",
          "Add WATSONX_PROJECT_ID=<your_project_id> to AgriDoctor/.env")
else:
    is_uuid = len(project_id) == 36 and project_id.count("-") == 4
    _ok(f"WATSONX_PROJECT_ID present (len={len(project_id)}, uuid_format={is_uuid})")
    if not is_uuid:
        _fail(
            f"WATSONX_PROJECT_ID format unexpected (len={len(project_id)}, "
            "expected 36-char UUID xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)",
            "Copy the Project ID from: watsonx.ai → your project → Manage → General",
        )

# WATSONX_URL check
_ok(f"WATSONX_URL = {url}")
if not url.startswith("https://"):
    _fail("WATSONX_URL must begin with https://",
          "Set WATSONX_URL=https://us-south.ml.cloud.ibm.com (or your region)")

if _FAIL > 0:
    print(f"\n  {_FAIL} structural check(s) failed — fix above and re-run.")
    sys.exit(1)
else:
    print("  All structural checks passed.")

# ════════════════════════════════════════════════════════════════════════════
# Step 3 — SDK import
# ════════════════════════════════════════════════════════════════════════════
print()
print("=" * 60)
print("Step 3 : ibm-watsonx-ai SDK import")
print("=" * 60)
try:
    import ibm_watsonx_ai as _sdk
    from ibm_watsonx_ai import Credentials
    from ibm_watsonx_ai.foundation_models import ModelInference
    sdk_ver = getattr(_sdk, "__version__", "unknown")
    _ok(f"ibm_watsonx_ai {sdk_ver} imported successfully")
except ImportError as exc:
    _fail(str(exc), "pip install ibm-watsonx-ai>=1.1.0")
    sys.exit(1)

# ════════════════════════════════════════════════════════════════════════════
# Step 4 — Credentials() object creation
# ════════════════════════════════════════════════════════════════════════════
print()
print("=" * 60)
print("Step 4 : Credentials() instantiation (no network call)")
print("=" * 60)
try:
    creds = Credentials(api_key=api_key, url=url)
    _ok(f"Credentials(url={url}) created")
except Exception as exc:
    _fail(f"Credentials() raised: {exc}")
    sys.exit(1)

# ════════════════════════════════════════════════════════════════════════════
# Step 5 — IBM Cloud IAM token exchange (live network)
# ════════════════════════════════════════════════════════════════════════════
print()
print("=" * 60)
print("Step 5 : IBM Cloud IAM token exchange (live network call)")
print("=" * 60)
print("  POST https://iam.cloud.ibm.com/identity/token")

iam_url = "https://iam.cloud.ibm.com/identity/token"
iam_data = (
    "grant_type=urn:ibm:params:oauth:grant-type:apikey"
    f"&apikey={urllib.parse.quote(api_key)}"
).encode()
iam_req = urllib.request.Request(
    iam_url, data=iam_data,
    headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept":        "application/json",
    },
)
try:
    with urllib.request.urlopen(iam_req, timeout=20) as resp:
        iam_body = json.loads(resp.read())
    _ok(f"IAM exchange succeeded  (token_type={iam_body.get('token_type','?')}, "
        f"expires_in={iam_body.get('expires_in','?')}s)")
except urllib.error.HTTPError as exc:
    raw = exc.read().decode(errors="replace")
    _fail(f"IAM exchange HTTP {exc.code}")
    try:
        err_body = json.loads(raw)
        code = err_body.get("errorCode", "?")
        msg  = err_body.get("errorMessage", raw[:200])
        print(f"  IBM error code    : {code}")
        print(f"  IBM error message : {msg}")
    except Exception:
        print(f"  Response body : {raw[:300]}")
    print()
    if exc.code == 400 and "BXNIM0415E" in raw:
        print("  CAUSE  : The API key was not recognised by IBM Cloud IAM.")
        print("           This means the key was deleted, rotated, or belongs")
        print("           to a different IBM Cloud account.")
        print()
        print("  FIX:")
        print("    1. Log in to https://cloud.ibm.com")
        print("    2. Go to: Manage > Access (IAM) > API keys")
        print("    3. Create a NEW API key (shown only once — copy it immediately)")
        print("    4. Replace WATSONX_API_KEY in AgriDoctor/.env with the new key")
        print("    5. Re-run:  python AgriDoctor/tests/check_auth.py")
    elif exc.code == 400 and "BXNIM0410E" in raw:
        print("  CAUSE  : The API key format is invalid.")
        print("  FIX    : Regenerate the key from IBM Cloud IAM and update .env")
    elif exc.code == 401:
        print("  CAUSE  : Credentials rejected (key may lack required IAM permissions).")
    sys.exit(1)
except Exception as exc:
    _fail(f"Network error: {exc}",
          "Check your internet connection and firewall settings.")
    sys.exit(1)

# ════════════════════════════════════════════════════════════════════════════
# Step 6 — ModelInference() instantiation (validate=False, no API call)
# ════════════════════════════════════════════════════════════════════════════
print()
print("=" * 60)
print("Step 6 : ModelInference() instantiation")
print("         (validate=False — no foundation_model_specs API call)")
print("=" * 60)

vision_model_id = os.getenv("WATSONX_VISION_MODEL", "ibm/granite-vision-3-2-2b").strip()
text_model_id   = os.getenv("WATSONX_MODEL_ID",     "ibm/granite-vision-3-2-2b").strip()

print(f"  Vision model : {vision_model_id}")
print(f"  Text model   : {text_model_id}")

try:
    ModelInference(
        model_id=vision_model_id,
        credentials=creds,
        project_id=project_id,
        validate=False,
    )
    _ok(f"Vision ModelInference created")
except Exception as exc:
    _fail(f"Vision ModelInference failed: {exc}")

try:
    ModelInference(
        model_id=text_model_id,
        credentials=creds,
        project_id=project_id,
        validate=False,
    )
    _ok(f"Text ModelInference created")
except Exception as exc:
    _fail(f"Text ModelInference failed: {exc}")

# ════════════════════════════════════════════════════════════════════════════
# Step 7 — Project-to-WML association check
# ════════════════════════════════════════════════════════════════════════════
print()
print("=" * 60)
print("Step 7 : Project → WML service instance association check")
print("         (GET /ml/v1/foundation_model_specs)")
print("=" * 60)
print(f"  Project ID: {project_id[:8]}…")
print(f"  URL       : {url}")

# We need a bearer token from Step 5 to call the watsonx API
try:
    with urllib.request.urlopen(iam_req, timeout=20) as resp2:
        token = json.loads(resp2.read()).get("access_token", "")
except Exception:
    token = ""

specs_url = (
    f"{url}/ml/v1/foundation_model_specs"
    f"?version=2024-05-31&project_id={project_id}"
    f"&filters=%21lifecycle_withdrawn&limit=1"
)
specs_req = urllib.request.Request(
    specs_url,
    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
)
try:
    with urllib.request.urlopen(specs_req, timeout=20) as resp3:
        _ok("Project is associated with a WML instance — inference API accessible")
except urllib.error.HTTPError as exc:
    raw = exc.read().decode(errors="replace")
    _fail(f"HTTP {exc.code} from foundation_model_specs endpoint")
    try:
        err = json.loads(raw)
        for e in err.get("errors", [raw[:200]]):
            code = e.get("code", "?") if isinstance(e, dict) else "?"
            msg  = e.get("message", str(e)) if isinstance(e, dict) else str(e)
            print(f"  error code    : {code}")
            print(f"  error message : {msg}")
    except Exception:
        print(f"  response      : {raw[:300]}")
    print()
    if "no_associated_service_instance_error" in raw:
        print("  CAUSE  : The watsonx.ai Project is not linked to a Watson Machine")
        print("           Learning (WML) service instance.")
        print("           IAM authentication is WORKING — this is a project setup issue.")
        print()
        print("  FIX (choose one):")
        print()
        print("  Option A — Add a WML service instance to your existing project:")
        print("    1. Go to https://dataplatform.cloud.ibm.com/projects/")
        print("       (or https://eu-de.dataplatform.cloud.ibm.com for eu-de region)")
        print("    2. Open your project")
        print("    3. Go to: Manage tab > Services & integrations")
        print("    4. Click 'Associate service'")
        print("    5. Select or create a 'Watson Machine Learning' instance")
        print("    6. Click 'Associate'")
        print()
        print("  Option B — Create a new watsonx.ai project with WML pre-linked:")
        print("    1. Go to https://dataplatform.cloud.ibm.com/wx/home")
        print("    2. Click 'New project' > 'Create an empty project'")
        print("    3. Associate a WML instance during creation")
        print("    4. After creation, copy the new Project ID from:")
        print("       Manage tab > General > Project ID")
        print("    5. Update WATSONX_PROJECT_ID in AgriDoctor/.env")
        print("    6. Re-run:  python AgriDoctor/tests/check_auth.py")
    elif exc.code == 403:
        print("  CAUSE  : Access denied — the API key may lack the 'Editor' or")
        print("           'Viewer' role on the watsonx.ai project.")
        print("  FIX    : In IBM Cloud IAM, grant the API key access to the project.")
except Exception as exc:
    _fail(f"Network error: {exc}")

# ════════════════════════════════════════════════════════════════════════════
# Summary
# ════════════════════════════════════════════════════════════════════════════
print()
print("=" * 60)
if _FAIL == 0:
    print("  RESULT : ALL CHECKS PASSED")
    print("  The application is ready to make watsonx.ai inference calls.")
else:
    print(f"  RESULT : {_FAIL} check(s) failed — see FIX notes above.")
print("=" * 60)

sys.exit(0 if _FAIL == 0 else 1)
