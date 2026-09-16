import json, sys
REV = "6e83e00edcaef02b0cb1f2a783f9c6b9ed90a938"
ok = True
m = json.load(open("project-manifest.json"))
r = json.load(open("docs/decisions/route-evidence.json"))
if m["pinned_sources"]["almanak_sdk"]["rev"] != REV:
    print("FAIL: manifest SDK rev mismatch"); ok = False
if r["pinned"]["almanak_sdk"] != REV:
    print("FAIL: route-evidence SDK rev mismatch"); ok = False
allowed = {"VERIFIED", "SUPPORTED", "BLOCKED-UNKNOWN", "REJECTED"}
for layer in r["layers"]:
    if layer["status"] not in allowed:
        print("FAIL: bad status", layer["id"], layer["status"]); ok = False
    if not layer.get("boundary"):
        print("FAIL: layer has no evidence boundary:", layer["id"]); ok = False
if not any(l["id"] == "L6-morpho-address-registry-keying" and l["status"] == "REJECTED"
           for l in r["layers"]):
    print("FAIL: L6 must record the Base Sepolia rejection"); ok = False
print("check-manifests:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
