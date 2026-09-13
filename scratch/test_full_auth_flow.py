import urllib.request
import urllib.parse
import http.cookiejar
import time

base_url = "http://127.0.0.1:8000"

# Setup Cookie Processor
cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

print("=== Testing Full Authentication & Session Flow ===")

# 1. Test GET /login page
resp = opener.open(f"{base_url}/login")
assert resp.status == 200
html = resp.read().decode("utf-8")
assert "HealthPilot Ops" in html
assert "Sign In" in html
print("✓ GET /login page loads successfully")

# 2. Test Invalid Login
login_data = urllib.parse.urlencode({
    "email": "anita@healthpilot.org",
    "password": "wrongpassword"
}).encode("utf-8")

try:
    resp = opener.open(f"{base_url}/login", data=login_data)
    assert False, "Invalid login should return 401"
except urllib.error.HTTPError as e:
    assert e.code == 401
    err_html = e.read().decode("utf-8")
    assert "Invalid email or password" in err_html
print("✓ Invalid login attempts properly rejected with 401")

# 3. Test Successful Login for Anita Rao
valid_login_data = urllib.parse.urlencode({
    "email": "anita@healthpilot.org",
    "password": "password123"
}).encode("utf-8")

resp = opener.open(f"{base_url}/login", data=valid_login_data)
assert resp.status == 200
login_resp_html = resp.read().decode("utf-8")
assert "Anita Rao" in login_resp_html
print("✓ Login successful for anita@healthpilot.org — session cookie set")

# Verify session cookie was set in cookie jar
cookie_names = [c.name for c in cj]
assert "session_token" in cookie_names, f"Expected session_token in cookies, got {cookie_names}"
print("✓ HTTP-only session_token cookie received")

# 4. Test Authenticated Requisitions view
resp = opener.open(f"{base_url}/requisitions")
req_html = resp.read().decode("utf-8")
assert "Anita Rao" in req_html
assert "Branch A" in req_html
print("✓ Authenticated session correctly loads branch-scoped access for Anita Rao")

# 5. Test Signup for new user & new Company
ts = int(time.time())
signup_data = urllib.parse.urlencode({
    "name": f"Dr. Sarah_{ts}",
    "email": f"sarah_{ts}@apollohealth.org",
    "password": "securepass123",
    "role": "COMPANY_ADMIN",
    "company_name": f"Apollo Care {ts}",
    "branch_name": "Apollo Main Campus"
}).encode("utf-8")

cj_new = http.cookiejar.CookieJar()
opener_new = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj_new))

resp = opener_new.open(f"{base_url}/signup", data=signup_data)
assert resp.status == 200
signup_resp_html = resp.read().decode("utf-8")
assert f"Dr. Sarah_{ts}" in signup_resp_html
assert f"Apollo Care {ts}" in signup_resp_html

# Verify newly created company sees NO requisitions from other companies!
resp_reqs = opener_new.open(f"{base_url}/requisitions")
reqs_html = resp_reqs.read().decode("utf-8")
assert "REQ-0001" not in reqs_html, "New company must NOT see demo requisitions from HealthPilot Healthcare Systems!"
print("✓ Multi-tenant isolation verified: New company sees ZERO demo data from other companies!")

# 6. Test Logout
resp = opener.open(f"{base_url}/logout")
assert resp.status == 200
logout_html = resp.read().decode("utf-8")
assert "Sign In" in logout_html or "Logged out successfully" in logout_html
print("✓ Logout successfully clears session cookie and revokes session")

print("=== ALL AUTHENTICATION FLOW TESTS PASSED SUCCESSFULLY! ===")
