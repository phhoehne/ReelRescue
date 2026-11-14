#!/usr/bin/env python3
"""Retrieve an issued Apple ticket if stapler cannot resolve its delivery host.

HTTPS certificate verification remains enabled. No host/network settings change.
The caller must first confirm an Accepted notarization submission.
"""
import base64
import ipaddress
import json
from pathlib import Path
import re
import subprocess
import sys

HOST = "api.apple-cloudkit.com"
URL = f"https://{HOST}/database/1/com.apple.gk.ticket-delivery/production/public/records/lookup"


def attach(app):
    app = Path(app)
    signature = subprocess.run(["codesign","-dvvv",str(app)],capture_output=True,text=True,check=True).stderr
    match = re.search(r"^CDHash=([0-9a-f]{40})$",signature,re.M)
    if not match: raise RuntimeError("Could not determine app CDHash")
    name = "2/2/"+match[1]
    payload = json.dumps(dict(records=[dict(recordName=name)]))
    base = ["/usr/bin/curl","-fsS","--connect-timeout","5","--max-time","12"]
    args = ["-H","Content-Type: application/json","-d",payload,URL]
    request = subprocess.run(base+args,capture_output=True,text=True)
    if request.returncode:
        # Compare public DNS only after the regular delivery request fails.
        dns = subprocess.check_output(base+[f"https://dns.google/resolve?name={HOST}&type=A"],text=True)
        addresses = [r["data"] for r in json.loads(dns).get("Answer",[]) if r.get("type")==1]
        if not addresses: raise RuntimeError("Ticket server has no public IPv4 address")
        for address in addresses:
            ipaddress.IPv4Address(address)
            request = subprocess.run(base+["--resolve",f"{HOST}:443:{address}"]+args,capture_output=True,text=True)
            if request.returncode==0: break
    if request.returncode: raise RuntimeError("Apple ticket download failed: "+request.stderr)
    records = json.loads(request.stdout).get("records",[])
    record = next((r for r in records if r.get("recordName")==name and "fields" in r),None)
    if not record: raise RuntimeError("Apple has not issued a ticket for this app CDHash")
    ticket = base64.b64decode(record["fields"]["signedTicket"]["value"],validate=True)
    if not ticket: raise RuntimeError("Apple returned an empty ticket")
    path = app/"Contents/CodeResources"
    if path.is_symlink(): raise RuntimeError("Unexpected ticket symlink")
    path.write_bytes(ticket)
    print("Attached Apple-issued ticket through HTTPS fallback; verify with Gatekeeper.")


if __name__=="__main__": attach(sys.argv[1])
