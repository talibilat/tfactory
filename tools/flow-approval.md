# Flow approval

`tools/flow_approval.py` checks that a human approved a flow stage. The agent asks. The human signs with a key the agent cannot read. The agent then shows the signature, and the tool checks it against a file only root can change. The agent has no way to approve its own request.

## How it works

1. The agent calls `new_request(key, stage, context, reason)`. It gets a request with a random nonce (a one-time number) and an expiry time. The default life is 15 minutes. The longest life `verify` accepts is 1 hour.
2. The agent calls `payload(request)`. This gives the exact bytes to sign, in a fixed layout. The same request always gives the same bytes. Non-ASCII characters show as `\uXXXX`, so look-alike letters cannot hide in the text.
3. The human signs those bytes outside the agent's reach. See the steps below.
4. The agent calls `verify(request, signature_path)`. It returns `True` only when all of these hold.
   - The request has exactly the expected fields and has not expired.
   - `/etc/tstack/allowed_signers` and every directory above it belong to root and cannot be written by group or others. A symlink on the path, such as `/etc` on macOS (it points to `/private/etc`), must belong to root too. The tool checks both the path as written and the real path.
   - `/usr/bin/ssh-keygen -Y verify -f /etc/tstack/allowed_signers -I tstack-approver -n tstack-flow -s <signature>` exits 0 and prints `Good "tstack-flow" signature for tstack-approver`.

Any error returns `False`. That includes a missing file, a bad signature, a timeout and a request the tool cannot read. `verify` never raises.

Nothing reads an environment variable or a setting to change the trust file, the identity or the namespace. They are constants in the module.

## One-time setup (a human, with sudo)

Until this is done, no waiver can pass. `flow.py next` and `flow.py status` say so in one line under any blocked report: `Waivers are not set up on this machine. See tools/flow-approval.md. Blocked gates cannot be waived until then.`

Make a key pair on a machine or account the agent cannot reach. A hardware key (`ssh-keygen -t ed25519-sk`) is better still.

```sh
ssh-keygen -t ed25519 -f ~/approver_key -C tstack-approver
```

Write the public half into an `allowed_signers` file. Keep the `namespaces` option, so this key can only sign flow approvals.

```
tstack-approver namespaces="tstack-flow" ssh-ed25519 AAAA...your-public-key...
```

Install it as root.

```sh
sudo install -d -o root -g wheel -m 755 /etc/tstack
sudo install -o root -g wheel -m 644 allowed_signers /etc/tstack/allowed_signers
```

Check that the result is root owned all the way up.

```sh
ls -ld /etc /etc/tstack /etc/tstack/allowed_signers
```

On Linux, use `-g root` instead of `-g wheel`.

You can add `valid-before="YYYYMMDD"` to the line to make the key expire.

## Signing a request

The agent writes the bytes to sign and shows the request to the human.

```sh
python3 tools/flow_approval.py new ARPP-1234 merge "PR 99" "Checks pass" > request.json
python3 tools/flow_approval.py payload request.json payload.txt
cat payload.txt
```

The human reads `payload.txt` first. It names the ticket, the stage, the reason and the expiry. Only sign what you read and agree with. Then the human signs on their own machine, using the exact bytes the agent printed.

```sh
ssh-keygen -Y sign -f ~/approver_key -n tstack-flow payload.txt
```

This writes `payload.txt.sig`. It starts with `-----BEGIN SSH SIGNATURE-----`.

The human can return the signature through chat by pasting the whole block, including the BEGIN and END lines. The signature is public data, so pasting it is safe. The agent saves it to a file and checks it.

```sh
python3 tools/flow_approval.py verify request.json approval.sig
```

The command prints `approved` and exits 0, or prints `not approved` and exits 1. From Python, call `verify(request, "approval.sig")`. A request file that is not JSON, larger than 64 KiB, or nested too deeply for Python to read gives `error: ...` and exit 1.

Request the signature before the expiry time. A chat round trip fits in 15 minutes. If it takes longer, make a new request.

## What this does not protect against

The agent runs as the same user that owns the working files. These limits follow from that.

- Every file the agent can write is untrusted. That covers the request, the signature, any record of used nonces and any "approved" marker. The only trusted inputs are the root-owned trust file and the signing key.
- `verify` keeps no state. The same request and signature pass again until the request expires. Nothing here stops a replay inside that window. A caller that needs one-time use must record the nonce, and a record in a user-writable place can be deleted by the agent. Keep the window short, and tie each request to one key and stage so a replay can only repeat the same approved step.
- The module proves that a signature exists. It does not force anyone to call it. An agent that can edit the calling skill or this module can skip the check. Run the check in code the agent cannot change, or review changes to it.
- The human must read what they sign. A request that is misleading but well formed gets a valid signature.
- If the agent can run `sudo` without a password, it can rewrite the trust file and the root-owned guarantee is gone.
- If the agent can read the private key, for example because it sits in the agent's home folder, the agent can sign for itself. Keep the key elsewhere.
- Expiry uses the local clock. Changing the clock needs root.
- The checks run, then `ssh-keygen` opens the file. Only root can change the trust file and its parent directories, so a user cannot swap it in between. Root could.
- ACLs and macOS file flags are not inspected. Look at them with `ls -le` and `ls -lO` if the machine is shared.

## Tests

```sh
python3 tools/tests/test_flow_approval.py
```

The tests make disposable keys and directories under a temporary folder and sign with the real `ssh-keygen`. They never touch `/etc/tstack`. They change `TRUST_FILE` and `TRUSTED_UIDS` inside the test process only, because a temporary folder cannot be root owned. One test confirms that a rogue key fails against the real default path.
