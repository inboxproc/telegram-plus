#!/usr/bin/env python3
"""
Regenerate fake provisioning profiles for a custom bundle_id.

The fake-codesigning profiles are CMS-signed .mobileprovision files whose embedded
plist hardcodes `ph.telegra.Telegraph` (application-identifier, application-groups,
iCloud containers, merchant ids). When we switch telegram-plus-configuration.json
to a custom bundle_id, the embedded plist must match, otherwise:
  * Make.py's copy_profiles_from_directory() can't match profiles by
    team_id + '.' + bundle_id  -> app builds with NO valid aps-environment -> exit(1)
  * AppDelegate's `guard appGroupUrl` (line ~662) fails at runtime because the app
    looks for group.<new_bundle_id> which the embedded entitlements don't provide
    -> black screen.

This script runs on macOS (CI runner) where `security` + `codesign` are available.
It rewrites all occurrences of OLD_BUNDLE -> NEW_BUNDLE inside each profile's
embedded plist and re-signs the CMS envelope with the self-signed fake cert.

Usage:
  python3 build-system/Make/RegenerateProfilesForBundle.py \
    --profiles build-system/fake-codesigning/profiles \
    --certs-path build-system/fake-codesigning/certs \
    --old-bundle ph.telegra.Telegraph \
    --new-bundle ph.telegra.TelegramPlus

Requires the fake self-signed p12 + cer (already in build-system/fake-codesigning/certs).
"""
import argparse
import os
import plistlib
import subprocess
import sys
import tempfile


def run(args, check=True, capture=True):
    res = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and res.returncode != 0:
        sys.stderr.write("CMD FAILED: {}\n{}\n".format(" ".join(args), res.stderr.decode()))
        if res.stdout:
            sys.stderr.write(res.stdout.decode() + "\n")
        sys.exit(res.returncode)
    return res.stdout


def decode_plist(profile_path):
    """Extract embedded plist from a CMS-signed .mobileprovision via security cms."""
    out = run(["security", "cms", "-D", "-i", profile_path])
    return plistlib.loads(out)


def set_bundle_in_plist(d, old, new):
    """Recursively replace old->new in string values. Returns change count."""
    n = 0
    if isinstance(d, dict):
        for k in list(d.keys()):
            n += set_bundle_in_plist(d[k], old, new)
    elif isinstance(d, list):
        n += sum(set_bundle_in_plist(x, old, new) for x in d)
    elif isinstance(d, str):
        if old in d:
            d = d.replace(old, new)
            n += 1
    # plistlib returns mutable dicts/lists we can update in-place for dict/list,
    # but str is immutable; for list elements we replaced value but need to write back.
    return n


def mutate_plist(d, old, new):
    """Recursive replace capable of updating list/dict element values (strings)."""
    n = 0
    if isinstance(d, dict):
        for k in list(d.keys()):
            v = d[k]
            if isinstance(v, str):
                if old in v:
                    d[k] = v.replace(old, new)
                    n += 1
            else:
                n += mutate_plist(v, old, new)
    elif isinstance(d, list):
        for i in range(len(d)):
            v = d[i]
            if isinstance(v, str):
                if old in v:
                    d[i] = v.replace(old, new)
                    n += 1
            else:
                n += mutate_plist(v, old, new)
    return n


def resign_cms(plist_bytes, keychain_name, signing_identity, dest):
    tmp = tempfile.mktemp()
    with open(tmp, "wb") as f:
        f.write(plist_bytes)
    run(["security", "cms", "-S", "-k", keychain_name, "-N", signing_identity, "-i", tmp, "-o", dest])
    os.unlink(tmp)


def setup_keychain(p12_path):
    kh = "regenerate-profiles-temp.keychain"
    kw = "temp123"
    run(["security", "delete-keychain", kh], check=False)
    run(["security", "create-keychain", "-p", kw, kh])
    existing = run(["security", "list-keychains", "-d", "user"]).decode().strip()
    run(["security", "list-keychains", "-d", "user", "-s", kh, existing.replace('"', '')])
    run(["security", "set-keychain-settings", kh])
    run(["security", "unlock-keychain", "-p", kw, kh])
    run(["security", "import", p12_path, "-k", kh, "-P", "", "-T", "/usr/bin/codesign", "-T", "/usr/bin/security"])
    run(["security", "set-key-partition-list", "-S", "apple-tool:,apple:", "-k", kw, kh])
    return kh, kw


def get_signing_identity(kh):
    """Extract the CN of the embedded codesigning cert from the temp keychain."""
    out = run(["security", "find-identity", "-p", "codesigning", kh]).decode()
    # line like: "  1) HASH "Apple Distribution: Telegram FZ-LLC (C67CF9S4VU)"
    for line in out.splitlines():
        if ")" in line and '"' in line:
            ident = line.split('"')[1]
            return ident
    print("No codesigning identity found in keychain:\n{}".format(out))
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profiles", required=True)
    ap.add_argument("--certs-path", required=True)
    ap.add_argument("--old-bundle", default="ph.telegra.Telegraph")
    ap.add_argument("--new-bundle", required=True)
    args = ap.parse_args()

    p12 = os.path.join(args.certs_path, "SelfSigned.p12")
    if not os.path.exists(p12):
        print("{} does not exist".format(p12))
        sys.exit(1)

    kh, kw = setup_keychain(p12)
    signing_identity = get_signing_identity(kh)
    print("Signing identity: {}".format(signing_identity))

    try:
        total = 0
        for fname in sorted(os.listdir(args.profiles)):
            if not fname.endswith(".mobileprovision"):
                continue
            fpath = os.path.join(args.profiles, fname)
            pl = decode_plist(fpath)
            n = mutate_plist(pl, args.old_bundle, args.new_bundle)
            if n == 0:
                print("{}: no {} refs -> re-signing unchanged".format(fname, args.old_bundle))
            else:
                print("{}: replaced {} ref(s) {} -> {}".format(fname, n, args.old_bundle, args.new_bundle))
            resign_cms(plistlib.dumps(pl), kh, signing_identity, fpath)
            total += 1
        print("Done. Resigned {} profile(s) for bundle {}".format(total, args.new_bundle))
    finally:
        run(["security", "delete-keychain", kh], check=False)


if __name__ == "__main__":
    main()
